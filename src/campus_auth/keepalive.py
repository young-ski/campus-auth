"""断线保活循环。

判定顺序刻意从便宜到贵：先查门户在线列表（一次请求就能确定），再探 DNS，
最后才登录。失败按指数退避，避免被网关当成扫描器拉黑。
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


@dataclass
class Cycle:
    online: bool
    attempted: bool
    ok: bool
    message: str


def one_cycle(
    portal: Portal, account: str, password: str, operator: str, probe_host: str = "www.baidu.com"
) -> Cycle:
    try:
        if portal.mine():
            return Cycle(online=True, attempted=False, ok=True, message="仍在线")
    except TransportError as exc:
        return Cycle(online=False, attempted=False, ok=False, message=f"查在线状态失败: {exc}")

    if net.resolves(probe_host):
        return Cycle(online=False, attempted=False, ok=True, message="DNS 正常，无需登录")

    result = portal.login(account, password, operator)
    if result.ok:
        try:
            if portal.mine():
                return Cycle(online=True, attempted=True, ok=True, message="已重新登录")
        except TransportError:
            pass
        return Cycle(
            online=False, attempted=True, ok=True, message=f"登录被接受但未确认在线: {result.msg}"
        )
    return Cycle(
        online=False,
        attempted=True,
        ok=False,
        message=f"登录失败: {result.msg} {result.hint}".strip(),
    )


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
    cycle_no = 0
    while True:
        cycle_no += 1
        try:
            portal = make_portal()
            cycle = one_cycle(portal, account, password, operator, probe_host)
        except CampusAuthError as exc:
            cycle = Cycle(
                online=False, attempted=False, ok=False, message=f"{type(exc).__name__}: {exc}"
            )
        except Exception as exc:  # 保活不能因为一次意外就退出
            cycle = Cycle(online=False, attempted=False, ok=False, message=f"意外错误: {exc!r}")

        on_cycle(cycle, cycle_no)
        failures = 0 if cycle.ok else failures + 1
        if once or (max_cycles is not None and cycle_no >= max_cycles):
            return 0 if cycle.ok else 1

        delay = interval * (1 + random.uniform(-jitter, jitter))
        if failures:
            delay = min(backup, delay * 2 ** min(failures, 4))
        sleep(max(5.0, delay))
