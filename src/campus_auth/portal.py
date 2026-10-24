"""Portal 传输与业务动作。

只做三件事：拼 URL、发请求、把响应翻译成 `LoginResult` / 会话列表。
任何"某所学校特有的东西"都来自适配层，这里不含硬编码学校逻辑。

禁用证书校验是刻意为之：校园门户清一色自签证书，而且不少还停在
TLS 1.0 + SHA1（所以要把 SECLEVEL 降到 0）。
"""

from __future__ import annotations

import contextlib
import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .adapters.base import Adapter, LoginResult, Param
from .errors import RejectedError, TransportError

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) campus-auth"


def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(ssl.SSLError):  # 个别 OpenSSL 构建没有该级别
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    return ctx


def extract_json(body: str) -> dict[str, Any]:
    """从 JSONP 响应里挖出对象。

    `dr1003({...})` / `jsonp123({...})` / 纯 JSON 都要能吃下去，所以按括号
    配平扫描，而不是正则 `\\{.*\\}`（后者会被字符串里的花括号带偏）。
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
    raise TransportError(f"响应里没有可解析的 JSON 对象: {body[:200]!r}")


@dataclass
class Session:
    account: str = ""
    ip: str = ""
    mac: str = ""
    time_long: str = ""
    uplink: str = ""
    downlink: str = ""
    raw: Mapping[str, Any] | None = None


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
    ) -> None:
        adapter.check()
        self.adapter = adapter
        self.base_url = (base_url or adapter.base_url).rstrip("/")
        self.verify_tls = adapter.verify_tls if verify_tls is None else verify_tls
        self.timeout = timeout or adapter.timeout
        self.retries = max(0, retries)
        self.ip = ip
        self.mac = mac or "0" * 12
        self._ctx = _ssl_context(self.verify_tls)
        self.last_url = ""

    # ---------- 传输 ----------

    def build_url(self, path: str, params: list[Param]) -> str:
        """按适配层的编码规则拼出完整 URL（生成快捷方式也走这里）。"""
        enc = self.adapter.encoder(self.ip)
        pairs = [(p.key, enc(p.value) if p.encode else p.value) for p in params]
        query = urllib.parse.urlencode(pairs, safe="@,.:")
        return f"{self.base_url}{path}?{query}"

    def get(self, path: str, params: list[Param]) -> dict[str, Any]:
        url = self.build_url(path, params)
        self.last_url = url
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(
                    request, context=self._ctx, timeout=self.timeout
                ) as resp:
                    body = resp.read().decode("utf-8", "replace")
                return extract_json(body)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if exc.code in (429, 503):
                    delay = float(exc.headers.get("Retry-After") or 0) or 2.0 * (attempt + 1)
                    if attempt < self.retries:
                        time.sleep(delay)
                        continue
                return extract_json(body) if "{" in body else _raise_http(exc, body)
            except (urllib.error.URLError, TimeoutError, OSError, TransportError) as exc:
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

    # ---------- 动作 ----------

    def online(self) -> list[Session]:
        payload = self.get(self.adapter.online_path, self.adapter.online_params())
        rows = payload.get("list") or []
        return [
            Session(
                account=str(row.get("user_account") or ""),
                ip=str(row.get("online_ip") or ""),
                mac=str(row.get("online_mac") or ""),
                time_long=str(row.get("time_long") or ""),
                uplink=str(row.get("uplink_bytes") or ""),
                downlink=str(row.get("downlink_bytes") or ""),
                raw=row,
            )
            for row in rows
            if isinstance(row, dict)
        ]

    def mine(self) -> Session | None:
        for row in self.online():
            if self.adapter.row_is_mine(row.raw or {}, self.ip, self.mac):
                return row
        return None

    def login(self, account: str, password: str, operator: str = "none") -> LoginResult:
        params = self.adapter.login_params(
            ip=self.ip, mac=self.mac, account=account, password=password, operator=operator
        )
        payload = self.get(self.adapter.login_path, params)
        return self.adapter.interpret_login(payload)

    def logout(self) -> dict[str, Any]:
        return self.get(
            self.adapter.logout_path, self.adapter.logout_params(ip=self.ip, mac=self.mac)
        )

    def unbind(self, account: str) -> dict[str, Any]:
        return self.get(
            self.adapter.unbind_path,
            self.adapter.unbind_params(ip=self.ip, mac=self.mac, account=account),
        )


def _raise_http(exc: urllib.error.HTTPError, body: str) -> dict[str, Any]:
    raise TransportError(f"HTTP {exc.code} {exc.reason}: {body[:200]!r}") from exc


def iter_retry_delays(attempts: int, base: float = 1.5, cap: float = 60.0) -> Iterator[float]:
    for i in range(attempts):
        yield min(cap, base * (2**i))


__all__ = ["Portal", "Session", "extract_json", "RejectedError"]
