"""门户指纹识别：判断某地址是哪家认证门户（Dr.COM / 锐捷 / 深澜）。

只碰匿名接口 —— 根页面、`online_list` 之类的公开路径，不需要账号密码。
结论分四档，宁可说"证据不足"也不硬猜，因为猜错的代价是别人 clone 下来
配半天适配层，跑起来才发现方向全错。

打分是纯函数 `analyze()`，网络部分 `collect()` 只负责取样，方便测试。
权重按"谁独有"排：`interface.do`、`srun_portal`、`enc_pwd` 这种给高权，
JSONP 回显、`result` 字段这类谁都会有的给低权；两家分数咬得太紧就只给
`likely-drcom` 并说明分不开（`THRESHOLD` / `MARGIN`）。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .errors import ConfigError, TransportError
from .transport import MAX_BODY, Response, Transport, UrllibTransport

MAX_JS = 1  # 指纹基本都在第一个脚本里，多抓只是拖慢

# 探针路径：都是匿名可访问的，且 Dr.COM / 锐捷 / 深澜 的反应互不相同。
# 锐捷的劫持页本身不带指纹，多问一句它的 index.jsp 和 InterFace.do 才看得见 InterFace.do。
PROBE_PATHS = (
    "/",
    "/eportal/index.jsp",
    "/eportal/portal/online_list?callback=probe1003&lang=zh",
    "/eportal/InterFace.do?method=getOnlineUserInfo",
)

_JS_SRC = re.compile(r"""<script[^>]+src=["']([^"']+\.js[^"']*)["']""", re.IGNORECASE)
# 劫持页把我们指去门户时，跟着走一步
_CAPTIVE = re.compile(
    r"""(?:location(?:\.href)?\s*=\s*|url\s*=\s*)['"]?(https?://[^'"\s>]{4,})""", re.IGNORECASE
)


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
# 权重按"哪家独有"排：独有特征给高权重，通用 JSONP 行为给低权重。
DRCOM_SIGNALS: list[tuple[str, int, str, str, str | re.Pattern[str]]] = [
    ("页面 / JS 里出现 dr1003 一类回调", 35, "drcom", "all", re.compile(r"\bdr100[345]\b")),
    ("JS 里有 enc_pwd（异或加密函数）", 30, "drcom", "js", "enc_pwd"),
    ("JS 里有 getkey（密钥派生）", 25, "drcom", "js", "getkey"),
    ("出现 wlan_user_ip 参数", 20, "drcom", "all", "wlan_user_ip"),
    (
        "响应含 ret_code / result 字段",
        15,
        "drcom",
        "body",
        re.compile(r'"(?:ret_code|result)"\s*:'),
    ),
    ("JS 里有 jsVersion 参数", 15, "drcom", "all", "jsVersion"),
    ("出现 Dr.COM / 城市热点 字样", 15, "drcom", "all", re.compile(r"dr\.?com|城市热点", re.I)),
    ("有 eportal/portal/login 路径", 15, "drcom", "all", "eportal/portal/login"),
    ("有 eportal/portal/online_list 接口", 15, "drcom", "all", "eportal/portal/online_list"),
    (
        "匿名接口回显了自己传的 callback（JSONP 可用）",
        10,
        "drcom",
        "body",
        re.compile(r"\bprobe1003\s*\("),
    ),
    # nginx 对任何 80/443/8080 的站点都成立，只值半分
    ("Server 是 nginx 且端口像网关", 5, "drcom", "server", ""),
]

RUIJIE_SIGNALS: list[tuple[str, int, str, str, str | re.Pattern[str]]] = [
    ("出现 InterFace.do 接口", 40, "ruijie", "all", re.compile(r"interface\.do", re.I)),
    (
        "驼峰参数 userAccount / userPassword",
        35,
        "ruijie",
        "all",
        re.compile(r"useraccount|userpassword", re.I),
    ),
    ("出现 userIndex 字段", 20, "ruijie", "all", re.compile(r"userindex", re.I)),
    ("出现 锐捷 / ruijie 字样", 15, "ruijie", "all", re.compile(r"ruijie|锐捷", re.I)),
    ("有 index_1.jsp / index_1.js", 10, "ruijie", "all", re.compile(r"index_1\.(?:jsp|js)")),
    ("eportal 路径但无 jsVersion", 10, "ruijie", "eportal-no-jsversion", ""),
]

SRUN_SIGNALS: list[tuple[str, int, str, str, str | re.Pattern[str]]] = [
    ("srun_portal 接口", 40, "srun", "all", "srun_portal"),
    ("get_challenge 接口", 35, "srun", "all", "get_challenge"),
    ("出现 {SRBX1} / {SRBX2} 密文前缀", 25, "srun", "all", re.compile(r"\{srbx[12]\}")),
    ("出现 ac_id 参数", 20, "srun", "all", "ac_id"),
    ("出现 深澜 字样", 20, "srun", "all", "深澜"),
    ("srun_bx1 / srun_chap 参数", 10, "srun", "all", re.compile(r"srun_bx1|srun_chap")),
]

# 各家认定的门槛，以及必须领先第二名多少分 —— 差得不多就只给"证据不全"。
THRESHOLD = {"drcom": 55, "ruijie": 35, "srun": 40}
MARGIN = 10

# 通用信号（wlan_user_ip、result 字段、nginx）谁都可能有，分数能凑够也不代表是它。
# 判成"是 Dr.COM"必须有一条独有特征撑着。
DISTINCTIVE = ("enc_pwd", "getkey")


def analyze(samples: Mapping[str, str], *, server: str = "", port: int | None = None) -> Analysis:
    """按样本打分。`samples` 的键是路径，另需可选的 `server` 头与 `port`。"""
    all_text = "\n".join(samples.values()).lower()
    body_text = samples.get("body", "").lower()
    js_text = samples.get("js", "").lower()
    eportal = "eportal" in all_text
    has_jsversion = "jsversion" in all_text
    scopes = {"all": all_text, "body": body_text, "js": js_text}

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

    notes: list[str] = []
    missing: list[str] = []
    if not samples:
        return Analysis(
            "unknown", 0, evidence, ["没拿到任何响应"], ["检查地址、端口，以及是否在校园网内"]
        )

    # 先看别的门户是否明显更像，再谈 Dr.COM：锐捷/深澜也会回显 callback、
    # 也可能吐 result/ret_code，光凭这两条会把它们误判成 Dr.COM。
    # 领先不够就叫"证据不全"，宁可让人再抓一次包，也别把人指到错的适配层。
    scores = {"drcom": drcom, "ruijie": ruijie, "srun": srun}
    ranked = sorted(scores, key=lambda name: scores[name], reverse=True)
    best, runner_up = ranked[0], ranked[1]
    decisive = scores[best] >= THRESHOLD[best] and scores[best] - scores[runner_up] >= MARGIN
    if decisive and best == "drcom":
        # 凑够分还不够：独有特征得真的命中
        decisive = any(
            signal.hit and any(word in signal.name for word in DISTINCTIVE) for signal in evidence
        )

    if decisive:
        verdict = best
    elif drcom >= 25:
        verdict = "likely-drcom"
        if scores[runner_up] >= 25:
            notes.append(
                f"Dr.COM 与 {runner_up} 的特征分不开（{drcom} vs {scores[runner_up]}），"
                "先按 Dr.COM 试，不行再换"
            )
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


def _absorb(url: str, fetch, js_chunks: list[str]) -> str:
    """取一个页面，顺手抓它的 JS；取不到就返回空串。"""
    try:
        text = fetch(url).text
    except TransportError:
        return ""
    for src in _JS_SRC.findall(text)[:MAX_JS]:
        js_url = urllib.parse.urljoin(url, src)
        try:
            js_chunks.append(fetch(js_url).text)
        except TransportError:
            continue
    return text


def collect(
    base_url: str,
    *,
    timeout: float = 8.0,
    verify: bool = False,
    transport: Transport | None = None,
    follow: bool = True,
    retries: int = 0,
    info: dict[str, object] | None = None,
) -> tuple[dict[str, str], str, int | None]:
    """按 PROBE_PATHS 采样，并顺带抓 1 个 JS（可跨源，路径由页面自己给）。

    返回 (样本, Server 头, 端口)。sample 只含 body / js，头信息单独给。
    根页面若只是劫持跳转（锐捷常态），会跟着它给的地址再走一步。
    """
    parts = urllib.parse.urlsplit(base_url)
    if not parts.hostname:
        raise ConfigError(f"看不懂的地址: {base_url!r}，要 http(s)://host[:port]")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise ConfigError(f"{base_url!r} 的端口不合法（{exc}）") from exc
    send = transport or UrllibTransport(verify_tls=verify)

    def fetch(url: str, limit: int = MAX_BODY) -> Response:
        last: Exception | None = None
        for attempt in range(max(0, retries) + 1):
            try:
                return send.send(url, timeout=timeout, limit=limit)
            except TransportError as exc:
                last = exc
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
        assert last is not None
        raise last

    samples: dict[str, str] = {}
    server = ""
    js_chunks: list[str] = []
    ok = 0

    def grab(path: str) -> tuple[str, str, Response] | None:
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        try:
            return path, url, fetch(url)
        except TransportError:
            return None

    # 四条路径并发：校园网慢的时候不至于按 4 倍超时等
    with ThreadPoolExecutor(max_workers=len(PROBE_PATHS)) as pool:
        for got in pool.map(grab, PROBE_PATHS):
            if got is None:
                continue
            path, url, response = got
            ok += 1
            server = server or response.headers.get("server", "")
            text = response.text
            samples["body"] = text if path == "/" else samples.get("body", "") + "\n" + text
            if path == "/":
                for src in _JS_SRC.findall(text)[:MAX_JS]:
                    js_url = urllib.parse.urljoin(url, src)
                    try:
                        js_chunks.append(fetch(js_url).text)
                    except TransportError:
                        continue

    # 劫持页只给一句 location.href，指纹全在它指向的门户页上。
    # 跟不跟由调用方决定（--no-follow），一跳为止。
    captive = _CAPTIVE.search(samples.get("body", "")) if follow else None
    if captive:
        target = captive.group(1)
        page = _absorb(target, fetch, js_chunks)
        if page:
            samples["body"] = samples.get("body", "") + "\n" + page
            if info is not None:
                info["followed"] = target

    if not ok:
        raise TransportError(f"{base_url} 一条探针都没通 —— 多半不在校园网内，或端口/协议写错了")
    if js_chunks:
        samples["js"] = "\n".join(js_chunks)
    samples.setdefault("body", "")
    return samples, server, port


def probe(
    base_url: str,
    *,
    timeout: float = 8.0,
    verify: bool = False,
    transport: Transport | None = None,
    follow: bool = True,
    retries: int = 0,
) -> tuple[Analysis, str]:
    info: dict[str, object] = {}
    samples, server, port = collect(
        base_url,
        timeout=timeout,
        verify=verify,
        transport=transport,
        follow=follow,
        retries=retries,
        info=info,
    )
    analysis = analyze(samples, server=server, port=port)
    followed = info.get("followed")
    if followed:
        host = urllib.parse.urlsplit(str(followed)).hostname or ""
        analysis.notes.append(f"跟着劫持跳转到了 {host}")
    return analysis, base_url


JSON_SCHEMA_VERSION = 1


def to_json(analysis: Analysis, base_url: str) -> str:
    return json.dumps(
        {"schema": JSON_SCHEMA_VERSION, "ok": True, "target": base_url, **analysis.to_dict()},
        ensure_ascii=False,
        indent=2,
    )
