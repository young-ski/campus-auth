"""把「门户只按单个 IP 回会话」的接口摊成一份在线名单。

`online_list` 只认 `wlan_user_ip`：给哪个 IP 就问哪个 IP，没人在线就返回
`result: 0`。门户没有「全体在线用户」接口，要名单只能按网段逐个地址问一遍。
这里只负责三件事：把网段展开成地址、并发去问、把会话收回来；打表还是写
CSV 由命令层决定。

并发用线程池：每条请求就是一次 HTTPS，标准库够用，也不必给项目加依赖。
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .adapters.base import Adapter, Param, Request
from .errors import ConfigError, TransportError
from .portal import Portal, Session, extract_json, session_from_row

# 整段 /8 是 1600 万个地址，再多就该分片了
MAX_TARGETS = 1_000_000

Progress = Callable[[int, int, int], None]


def _network(spec: str) -> Iterable[str]:
    try:
        network = ipaddress.ip_network(spec, strict=False)
    except ValueError as exc:
        raise ConfigError(f"网段写法不对: {spec!r}（{exc}）") from exc
    if network.version != 4:
        raise ConfigError(f"只支持 IPv4 网段: {spec!r}")
    return (str(ip) for ip in network.hosts())


def _wildcard(spec: str) -> Iterable[str]:
    prefix = spec[: -len("*")].rstrip(".")
    try:
        base = ipaddress.ip_network(f"{prefix}.0/24", strict=False)
    except ValueError as exc:
        raise ConfigError(f"通配地址写法不对: {spec!r}（{exc}）") from exc
    # .0 与 .255 不会分给终端，和 /24 的 hosts() 保持一致
    return (str(ip) for ip in base.hosts())


def _span(spec: str) -> Iterable[str]:
    start_text, _, end_text = spec.partition("-")
    start_text, end_text = start_text.strip(), end_text.strip()
    try:
        start = ipaddress.IPv4Address(start_text)
    except ValueError as exc:
        raise ConfigError(f"起止地址写法不对: {spec!r}（{exc}）") from exc
    if end_text.isdigit():
        end = ipaddress.IPv4Address(f"{start_text.rsplit('.', 1)[0]}.{end_text}")
    else:
        try:
            end = ipaddress.IPv4Address(end_text)
        except ValueError as exc:
            raise ConfigError(f"起止地址写法不对: {spec!r}（{exc}）") from exc
    if int(end) < int(start):
        raise ConfigError(f"起止地址反了: {spec!r}")
    return (str(ipaddress.IPv4Address(value)) for value in range(int(start), int(end) + 1))


def expand(spec: str) -> list[str]:
    """展开一条网段写法：CIDR / `a.b.c.*` / `a.b.c.1-254` / 单个 IP。"""
    spec = spec.strip()
    if not spec:
        return []
    if "/" in spec:
        return list(_network(spec))
    if spec.endswith("*"):
        return list(_wildcard(spec))
    if "-" in spec:
        return list(_span(spec))
    try:
        return [str(ipaddress.IPv4Address(spec))]
    except ValueError as exc:
        raise ConfigError(f"地址写法不对: {spec!r}（{exc}）") from exc


def parse_targets(specs: Iterable[str]) -> list[str]:
    """展开多条写法，按出现顺序去重；超过上限直接拒，别让人干等。"""
    targets: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        for part in spec.split(","):
            if not part.strip():
                continue
            for ip in expand(part):
                if ip in seen:
                    continue
                seen.add(ip)
                targets.append(ip)
                if len(targets) > MAX_TARGETS:
                    raise ConfigError(f"地址超过 {MAX_TARGETS} 个，缩小 --range 或分几次扫")
    return targets


@dataclass
class ScanOutcome:
    sessions: list[Session] = field(default_factory=list)
    scanned: int = 0
    failed: int = 0
    cancelled: bool = False


def _rows_for(portal: Portal, adapter: Adapter, ip: str, timeout: float) -> list[dict]:
    request = Request(
        path=adapter.online_path,
        params=[*adapter.online_params(), Param("wlan_user_ip", ip, encode=False)],
    )
    url = portal.build_url(request)
    status, text = portal.raw(url, timeout=timeout)
    if status >= 400:
        raise TransportError(f"HTTP {status}: {url}")
    payload = extract_json(text)
    return [
        row
        for row in adapter.interpret_sessions(payload)
        if isinstance(row, dict) and row.get("online_ip")
    ]


def scan(
    portal: Portal,
    adapter: Adapter,
    targets: list[str],
    *,
    workers: int = 64,
    timeout: float = 8.0,
    progress: Progress | None = None,
    report_every: float = 1.0,
) -> ScanOutcome:
    """逐个地址问会话。单个 IP 失败只计数，不打断整次扫描。

    进度回调大约每 `report_every` 秒一次，参数是（已扫、总数、已命中）。
    Ctrl-C 会停下未开始的请求并返回已扫到的部分，`cancelled` 置真。
    """
    outcome = ScanOutcome()
    total = len(targets)
    lock = threading.Lock()
    last_report = time.monotonic()

    def one(ip: str) -> tuple[str, list[dict]]:
        return ip, _rows_for(portal, adapter, ip, timeout)

    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futures = {pool.submit(one, ip): ip for ip in targets}
    try:
        for future in as_completed(futures):
            try:
                _, rows = future.result()
            except Exception:  # 超时、连接断、页面改版都只算这一个地址失败
                with lock:
                    outcome.failed += 1
            else:
                with lock:
                    outcome.sessions.extend(session_from_row(row) for row in rows)
            with lock:
                outcome.scanned += 1
                done = outcome.scanned
                hits = len(outcome.sessions)
            now = time.monotonic()
            if progress and now - last_report >= report_every:
                last_report = now
                progress(done, total, hits)
    except KeyboardInterrupt:
        outcome.cancelled = True
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        return outcome
    finally:
        if not outcome.cancelled:
            pool.shutdown(wait=True)

    outcome.sessions.sort(key=lambda session: ipaddress.IPv4Address(session.ip))
    return outcome
