"""断线保活循环。

判定顺序刻意简单：门户的会话列表是唯一一手证据，说不在线就登录。DNS 只在
登录被拒之后查一次，用来把「也许你其实在线」这类含糊情况写进日志。

失败按指数退避，避免被网关当成扫描器拉黑；但连续 `DNS_FALLBACK_AFTER` 轮
「被拒 + DNS 通」之后按健康处理，否则门户会话接口一坏就会退避到 8 倍间隔。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import net
from .errors import CampusAuthError, TransportError
from .portal import Portal

Sleeper = Callable[[float], None]

# 连续多少轮「认证被拒但 DNS 通」之后停止加长间隔
DNS_FALLBACK_AFTER = 3


@dataclass
class Cycle:
    online: bool
    attempted: bool
    ok: bool
    message: str
    elapsed: float = 0.0  # 这一轮耗时（秒），由 watch 填
    dns_ok: bool = False  # 本轮被拒时 DNS 是否仍然通（仅作归因）
    degraded: bool = False  # 已按「被拒但 DNS 通」的兜底处理，不再加长间隔


def _dns_ok(probe_host: str) -> bool:
    try:
        return net.resolves(probe_host)
    except OSError:  # 极端情况下 getaddrinfo 抛的不是 OSError 子类
        return False


def one_cycle(
    portal: Portal,
    account: str = "",
    password: str = "",
    operator: str = "",
    probe_host: str = "www.baidu.com",
) -> Cycle:
    """一轮检查 + 必要时的重登。account 等参数仅为兼容旧调用，实际从 portal 取。"""
    try:
        if portal.mine():
            return Cycle(online=True, attempted=False, ok=True, message="仍在线")
    except TransportError as exc:
        return Cycle(online=False, attempted=False, ok=False, message=f"查在线状态失败: {exc}")

    result = portal.login()
    if result.ok:
        try:
            if portal.mine():
                return Cycle(online=True, attempted=True, ok=True, message="已重新登录")
        except TransportError:
            pass
        return Cycle(
            online=False, attempted=True, ok=True, message=f"登录被接受但未确认在线: {result.msg}"
        )

    message = f"登录失败: {result.msg} {result.hint}".strip()
    dns_ok = _dns_ok(probe_host)
    if dns_ok:
        message += "（DNS 正常：可能其实已在线，或门户会话接口异常）"
    return Cycle(online=False, attempted=True, ok=False, message=message, dns_ok=dns_ok)


def watch(
    make_portal: Callable[[], Portal],
    *,
    account: str,
    password: str,
    operator: str,
    interval: float = 120.0,
    jitter: float = 0.3,
    probe_host: str = "www.baidu.com",
    once: bool = False,
    max_cycles: int | None = None,
    backup: float = 1800.0,
    sleep: Sleeper = time.sleep,
    on_cycle: Callable[[Cycle, int], None] = lambda cycle, _: None,
) -> int:
    """循环保活；返回最后一次是否健康（0/1）。"""
    failures = 0
    dns_streak = 0
    cycle_no = 0
    while True:
        cycle_no += 1
        started = time.monotonic()
        try:
            portal = make_portal()
            cycle = one_cycle(portal, account, password, operator, probe_host)
        except CampusAuthError as exc:
            cycle = Cycle(
                online=False, attempted=False, ok=False, message=f"{type(exc).__name__}: {exc}"
            )
        except Exception as exc:  # 保活不能因为一次意外就退出
            cycle = Cycle(online=False, attempted=False, ok=False, message=f"意外错误: {exc!r}")

        cycle.elapsed = time.monotonic() - started
        dns_streak = dns_streak + 1 if cycle.dns_ok else 0
        if not cycle.ok and dns_streak >= DNS_FALLBACK_AFTER:
            # 门户会话接口可能坏了：DNS 通说明链路大概没问题，别一路退避
            cycle.ok = True
            cycle.degraded = True
            cycle.message += f"（连续 {dns_streak} 轮被拒但 DNS 通，暂不再加长间隔）"
        failures = 0 if cycle.ok else failures + 1
        on_cycle(cycle, cycle_no)
        if once or (max_cycles is not None and cycle_no >= max_cycles):
            return 0 if cycle.ok else 1

        delay = interval * (1 + random.uniform(-jitter, jitter))
        if failures:
            delay = min(backup, delay * 2 ** min(failures, 4))
        sleep(max(5.0, delay))
