"""门户指纹识别：判断某地址是不是 Dr.COM，以及不是的话像什么。

只碰匿名接口 —— 根页面、`online_list` 之类的公开路径，不需要账号密码。
结论分四档，宁可说"证据不足"也不硬猜，因为猜错的代价是别人 clone 下来
配半天适配层，跑起来才发现方向全错。

打分是纯函数 `analyze()`，网络部分 `collect()` 只负责取样，方便测试。
"""

from __future__ import annotations

import contextlib
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field

from .errors import EnvironmentError_, TransportError

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) campus-auth/probe"
MAX_BODY = 200_000
MAX_JS = 3

# 探针路径：都是匿名可访问的，且 Dr.COM / 锐捷 / 深澜 的反应互不相同
PROBE_PATHS = (
    "/",
    "/eportal/portal/online_list?callback=probe1003&lang=zh",
)

_JS_SRC = re.compile(r"""<script[^>]+src=["']([^"']+\.js[^"']*)["']""", re.IGNORECASE)


@dataclass
class Signal:
    name: str
    weight: int
    hit: bool
    detail: str = ""


@dataclass
class Analysis:
    verdict: str  # drcom / likely-drcom / ruijie / srun / unknown
    score: int
    evidence: list[Signal] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_drcom(self) -> bool:
        return self.verdict in {"drcom", "likely-drcom"}

    @property
    def confidence(self) -> str:
        if self.score >= 70:
            return "高"
        if self.score >= 45:
            return "中"
        return "低"

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "is_drcom": self.is_drcom,
            "confidence": self.confidence,
            "score": self.score,
            "evidence": [
                {"name": s.name, "weight": s.weight, "hit": s.hit, "detail": s.detail}
                for s in self.evidence
            ],
            "missing": self.missing,
            "notes": self.notes,
        }


def _check(needle: str | re.Pattern[str], haystack: str) -> bool:
    if isinstance(needle, re.Pattern):
        return bool(needle.search(haystack))
    return needle.lower() in haystack


# (信号名, 权重, 归属, 在哪个样本里找, 匹配物)
DRCOM_SIGNALS: list[tuple[str, int, str, str, str | re.Pattern[str]]] = [
    ("页面 / JS 里出现 dr1003 一类回调", 35, "drcom", "all", re.compile(r"\bdr100[345]\b")),
    (
        "响应含 ret_code / result 字段",
        20,
        "drcom",
        "body",
        re.compile(r'"(?:ret_code|result)"\s*:'),
    ),
    (
        "匿名接口回显了自己传的 callback（JSONP 可用）",
        15,
        "drcom",
        "body",
        re.compile(r"\bprobe1003\s*\("),
    ),
    ("JS 里有 enc_pwd（异或加密函数）", 30, "drcom", "js", "enc_pwd"),
    ("JS 里有 getkey（密钥派生）", 25, "drcom", "js", "getkey"),
    ("JS 里有 jsVersion 参数", 20, "drcom", "all", "jsVersion"),
    ("出现 Dr.COM / 城市热点 字样", 15, "drcom", "all", re.compile(r"dr\.?com|城市热点", re.I)),
    ("出现 wlan_user_ip 参数", 15, "drcom", "all", "wlan_user_ip"),
    ("响应头 Set-Cookie 带 JSESSIONID", 5, "drcom", "headers", "jsessionid"),
]

RUIJIE_SIGNALS: list[tuple[str, int, str, str, str | re.Pattern[str]]] = [
    (
        "驼峰参数 userAccount / userPassword",
        35,
        "ruijie",
        "all",
        re.compile(r"useraccount|userpassword", re.I),
    ),
    ("出现 锐捷 / ruijie 字样", 20, "ruijie", "all", re.compile(r"ruijie|锐捷", re.I)),
    ("eportal 路径但无 jsVersion", 25, "ruijie", "eportal-no-jsversion", ""),
]

SRUN_SIGNALS: list[tuple[str, int, str, str, str | re.Pattern[str]]] = [
    ("srun_portal 接口", 40, "srun", "all", "srun_portal"),
    ("srun_bx1 / chap 参数", 20, "srun", "all", re.compile(r"srun_bx1|srun_chap")),
    ("出现 深澜 字样", 20, "srun", "all", "深澜"),
]

ELSEWHERE = [
    ("有 index_1.html / 锐捷样式", 10, "ruijie", "all", "index_1.html"),
    ("有 eportal/portal/login 路径", 10, "eportal", "all", "eportal/portal/login"),
    ("Server 是 nginx 且端口像网关", 5, "drcom", "server", ""),
]


def analyze(samples: Mapping[str, str], *, server: str = "", port: int | None = None) -> Analysis:
    """按样本打分。`samples` 的键是路径，另需可选的 `server` 头与 `port`。"""
    all_text = "\n".join(samples.values()).lower()
    body_text = samples.get("body", "").lower()
    js_text = samples.get("js", "").lower()
    headers = samples.get("headers", "").lower()
    eportal = "eportal" in all_text
    has_jsversion = "jsversion" in all_text
    scopes = {"all": all_text, "body": body_text, "js": js_text, "headers": headers}

    evidence: list[Signal] = []

    def run(table) -> int:
        total = 0
        for name, weight, _owner, scope, needle in table:
            if scope == "eportal-no-jsversion":
                hit = eportal and not has_jsversion
            elif scope == "server":
                hit = "nginx" in server.lower() and port in {802, 8080, 8443, 80, 443}
            else:
                hay = scopes.get(scope, "")
                hit = bool(hay) and _check(needle, hay)
            evidence.append(Signal(name, weight, hit))
            if hit:
                total += weight
        return total

    drcom = run(DRCOM_SIGNALS)
    ruijie = run(RUIJIE_SIGNALS)
    srun = run(SRUN_SIGNALS)
    run(ELSEWHERE)

    notes: list[str] = []
    missing: list[str] = []
    if not samples:
        return Analysis(
            "unknown", 0, evidence, ["没拿到任何响应"], ["检查地址、端口，以及是否在校园网内"]
        )

    # 先看别的门户是否明显更像，再谈 Dr.COM：锐捷/深澜也会回显 callback、
    # 也可能吐 result/ret_code，光凭这两条会把它们误判成 Dr.COM。
    if ruijie >= 40 and ruijie > drcom:
        verdict = "ruijie"
    elif srun >= 40 and srun > drcom:
        verdict = "srun"
    elif drcom >= 40:
        verdict = "drcom"
    elif drcom >= 25:
        verdict = "likely-drcom"
    elif eportal:
        verdict = "unknown"
        notes.append("看到 eportal 路径，但没有加密特征，无法区分 Dr.COM 与锐捷")
    else:
        verdict = "unknown"

    if verdict != "drcom":
        for name, weight, _o, _s, _n in DRCOM_SIGNALS:
            if not any(s.name == name and s.hit for s in evidence):
                missing.append(f"{name}（+{weight}）")

    if not eportal:
        notes.append("没找到 eportal 路径：可能不是网页认证门户，或登录前被重定向到别处")
    if not any(p in all_text for p in ("eportal", "srun", "userAccount".lower(), "<form")):
        notes.append("页面里既没有登录表单也没有已知门户特征，可能是路由器自带页面或另类门户")

    return Analysis(verdict, max(drcom, ruijie, srun), evidence, missing, notes)


# ---------- 取样 ----------


def _context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(ssl.SSLError):
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    return ctx


def _fetch(
    url: str, ctx: ssl.SSLContext, timeout: float, limit: int = MAX_BODY
) -> tuple[str, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, context=ctx, timeout=timeout) as resp:
            raw = resp.read(limit)
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
            return text, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        body = exc.read(limit).decode("utf-8", "replace")
        return body, {k.lower(): v for k, v in exc.headers.items()}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransportError(f"{url} 取不到: {exc}") from exc


def collect(
    base_url: str, *, timeout: float = 8.0, verify: bool = False
) -> tuple[dict[str, str], str, int | None]:
    """按 PROBE_PATHS 采样，并顺带抓最多 3 个同源 JS。

    返回 (样本, Server 头, 端口)。sample 键含 body / js / headers。
    """
    parts = urllib.parse.urlsplit(base_url)
    if not parts.hostname:
        raise EnvironmentError_(f"看不懂的地址: {base_url!r}，要 http(s)://host[:port]")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    ctx = _context(verify)

    samples: dict[str, str] = {}
    server = ""
    js_chunks: list[str] = []
    ok = 0

    for path in PROBE_PATHS:
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        try:
            text, headers = _fetch(url, ctx, timeout)
        except TransportError:
            continue
        ok += 1
        server = server or headers.get("server", "")
        samples["headers"] = (
            samples.get("headers", "")
            + "\n"
            + "\n".join(f"{k}: {v}" for k, v in headers.items() if k in {"server", "set-cookie"})
        )
        if path == "/":
            samples["body"] = text
            for src in _JS_SRC.findall(text)[:MAX_JS]:
                js_url = urllib.parse.urljoin(url, src)
                try:
                    chunk, _ = _fetch(js_url, ctx, timeout, limit=MAX_BODY)
                except TransportError:
                    continue
                js_chunks.append(chunk)
        else:
            samples["body"] = samples.get("body", "") + "\n" + text

    if not ok:
        raise TransportError(f"{base_url} 一条探针都没通 —— 多半不在校园网内，或端口/协议写错了")
    if js_chunks:
        samples["js"] = "\n".join(js_chunks)
    samples.setdefault("body", "")
    return samples, server, port


def probe(base_url: str, *, timeout: float = 8.0, verify: bool = False) -> tuple[Analysis, str]:
    samples, server, port = collect(base_url, timeout=timeout, verify=verify)
    return analyze(samples, server=server, port=port), base_url


def to_json(analysis: Analysis, base_url: str) -> str:
    return json.dumps({"target": base_url, **analysis.to_dict()}, ensure_ascii=False, indent=2)
