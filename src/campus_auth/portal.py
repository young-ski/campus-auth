"""Portal 传输与业务动作。

只做四件事：拼 URL、发请求、跟着适配层说的方式发、把响应翻译成
`LoginResult` / 会话列表。任何"某所学校特有的东西"都来自适配层。

禁用证书校验是刻意为之：校园门户清一色自签证书，而且不少还停在
TLS 1.0 + SHA1（所以要把 SECLEVEL 降到 0）。
"""

from __future__ import annotations

import contextlib
import datetime
import email.utils
import http.cookiejar
import json
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import NoReturn

from .adapters.base import Adapter, LoginResult, Request
from .errors import ParseError, TransportError

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) campus-auth"


_SECRET_PARAM = re.compile(r"(user_password|password)=([^&\s]{1,80})")


def _mask_url(url: str) -> str:
    """把 URL 里的密码值打掉。Dr.COM 的密文密钥就是同 URL 里的 IP，等于明文。"""

    def repl(match: re.Match[str]) -> str:
        value = match.group(2)
        if len(value) <= 4:
            return f"{match.group(1)}={value}"
        return f"{match.group(1)}={value[:2]}…{value[-2:]}"

    return _SECRET_PARAM.sub(repl, url)


def _retry_after(value: str | None, fallback: float) -> float:
    """解析 `Retry-After`：秒数或 HTTP 日期（RFC 9110 两种都允许）。

    解析不了就用 fallback；结果夹在 0.5～60 秒，别被服务端写的荒唐值拖住。
    """
    delay: float | None = None
    if value:
        try:
            delay = float(value.strip())
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                when = None
            if when is not None:
                now = datetime.datetime.now(when.tzinfo or None)
                delay = (when - now).total_seconds()
    if delay is None:
        return fallback
    return min(60.0, max(0.5, delay))


def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(ssl.SSLError):  # 个别 OpenSSL 构建没有该级别
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    return ctx


def extract_json(body: str) -> dict[str, object]:
    """从 JSONP 响应里挖出对象。

    `dr1003({...})` / `_({...})` / 纯 JSON 都要能吃下去，所以按括号配平扫描，
    而不是正则 `\\{.*\\}`（后者会被字符串里的花括号带偏）。
    """
    start = body.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(body)):
            ch = body[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(body[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = body.find("{", start + 1)
    raise ParseError(f"响应里没有可解析的 JSON 对象: {body[:200]!r}")


@dataclass
class Session:
    account: str = ""
    ip: str = ""
    mac: str = ""
    time_long: str = ""
    uplink: str = ""
    downlink: str = ""
    raw: Mapping[str, object] = field(default_factory=dict)


class Portal:
    def __init__(
        self,
        adapter: Adapter,
        *,
        base_url: str = "",
        verify_tls: bool | None = None,
        timeout: float | None = None,
        retries: int = 2,
        ip: str = "",
        mac: str = "",
        account: str = "",
        password: str = "",
        operator: str = "none",
        mask_urls: bool = True,
    ) -> None:
        adapter.check()
        self.adapter = adapter
        self.base_url = (base_url or adapter.base_url).rstrip("/")
        self.verify_tls = adapter.verify_tls if verify_tls is None else verify_tls
        self.timeout = timeout or adapter.timeout
        self.retries = max(0, retries)
        self.ip = ip
        self.mac = mac or "0" * 12
        self.account = account
        self.password = password
        self.operator = operator
        self.ctx: dict[str, object] = {}
        self.last_url = ""
        self.mask_urls = mask_urls
        self._ctx_tls = _ssl_context(self.verify_tls)
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))

    # ---------- 传输 ----------

    def build_url(self, request: Request) -> str:
        """按适配层的编码规则拼出完整 URL。"""
        enc = self.adapter.encoder(self.ip)
        pairs = [(p.key, enc(p.value) if p.encode else p.value) for p in request.params]
        query = urllib.parse.urlencode(pairs, safe="@,.:")
        url = request.path if request.is_absolute else f"{self.base_url}{request.path}"
        if not query:
            return url
        return f"{url}{'&' if '?' in url else '?'}{query}"

    def _body(self, request: Request) -> bytes:
        enc = self.adapter.encoder(self.ip)
        pairs = [(p.key, enc(p.value) if p.encode else p.value) for p in request.params]
        pairs += [(k, enc(v)) for k, v in request.body.items()]
        return urllib.parse.urlencode(pairs, safe="@,.:").encode()

    def request(self, request: Request) -> dict[str, object]:
        url = self.build_url(request)
        self.last_url = _mask_url(url) if self.mask_urls else url
        data = self._body(request) if request.method.upper() == "POST" else None
        headers = {"User-Agent": USER_AGENT, **request.headers}
        if data is not None:
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", "replace")
                return extract_json(body)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if exc.code in (429, 503) and attempt < self.retries:
                    delay = _retry_after(exc.headers.get("Retry-After"), 2.0 * (attempt + 1))
                    time.sleep(delay)
                    continue
                # 4xx/5xx 一律算失败：错误页里也可能带个 `{"result":0}`，别当成功
                _raise_http(exc, body)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1) + random.random())
                    continue
                # urllib 会把 SSL 错误包进 URLError.reason，这里拆出来给人话
                tls = getattr(exc, "reason", None)
                hint = ""
                if isinstance(tls, ssl.SSLError) or "SSL" in str(exc):
                    hint = "（TLS 握手失败：多半不在校园网内，或门户改过证书与端口）"
                raise TransportError(
                    f"请求失败，已重试 {self.retries} 次{hint}\n{self.last_url}\n{last}"
                ) from exc
        raise TransportError(f"请求失败（已重试 {self.retries} 次）: {self.last_url}\n{last}")

    def raw(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, str]:
        """发一次请求并原样返回 (状态码, 文本)，不解析 JSON。

        给"探页面 / 看 204"这类动作留着，适配层的 discover 用得上。
        """
        req = urllib.request.Request(
            url,
            data=body,
            headers={"User-Agent": USER_AGENT, **dict(headers or {})},
            method=method,
        )
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"请求失败: {url}\n{exc}") from exc

    # ---------- 动作 ----------

    def prepare(self) -> None:
        self.ctx = self.adapter.discover(self, self.account) or {}

    def sessions(self) -> list[Session]:
        payload = self.request(self.adapter.sessions_request(self))
        return [
            Session(
                account=str(row.get("user_account") or row.get("user_name") or ""),
                ip=str(row.get("online_ip") or ""),
                mac=str(row.get("online_mac") or ""),
                time_long=str(row.get("time_long") or row.get("add_time") or ""),
                uplink=str(row.get("uplink_bytes") or ""),
                downlink=str(row.get("downlink_bytes") or ""),
                raw=row,
            )
            for row in self.adapter.interpret_sessions(payload)
        ]

    def mine(self) -> Session | None:
        flag = self.adapter.online_check(self)
        if flag is not None:
            return Session(ip=self.ip, account=self.account) if flag else None
        for row in self.sessions():
            if self.adapter.row_is_mine(row.raw, self.ip, self.mac, self.account):
                return row
        return None

    def login(self) -> LoginResult:
        if not self.ctx:
            self.prepare()
        payload = self.request(self.adapter.login_request(self))
        result = self.adapter.interpret_login(payload)
        self.adapter.after_login(self, payload)
        return result

    def logout(self) -> dict[str, object]:
        if not self.ctx:
            self.prepare()
        return self.request(self.adapter.logout_request(self))

    def unbind(self) -> dict[str, object]:
        if not self.ctx:
            self.prepare()
        return self.request(self.adapter.unbind_request(self))


def _raise_http(exc: urllib.error.HTTPError, body: str) -> NoReturn:
    raise TransportError(f"HTTP {exc.code} {exc.reason}: {body[:200]!r}") from exc


def iter_retry_delays(attempts: int, base: float = 1.5, cap: float = 60.0) -> Iterator[float]:
    for i in range(attempts):
        yield min(cap, base * (2**i))


__all__ = ["Portal", "Session", "extract_json"]
