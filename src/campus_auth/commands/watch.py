"""保活循环。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ..keepalive import Cycle, watch
from ..logfile import RotatingLog, Tee
from ..runner import build
from ._common import _config, _dump, _say


def _startup_summary(config, ctx, interval: float, log_path: str | None) -> None:
    """跑之前把干的活说清楚：出了问题日志里得能对上号。"""
    _say(f"适配层 {ctx.adapter.name}  门户 {ctx.portal.base_url}")
    _say(f"账号 {config.account}  运营商 {config.operator}  IP {ctx.ip}  MAC {ctx.mac or '(空)'}")
    _say(f"间隔 {interval:g}s（±{config.jitter:.0%}）  单次超时 {config.timeout:g}s")
    if log_path:
        _say(f"日志 {log_path}")
    _say("Ctrl-C 停止；长期跑用 `campus-auth install` 装成登录自启")


def cmd_watch(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx_stub = build(config)  # 提前校验配置，失败就别进循环了

    log = None
    if args.log:
        log = RotatingLog(Path(args.log))
        sys.stdout = Tee(sys.stdout, log)  # type: ignore[assignment]
        sys.stderr = Tee(sys.stderr, log)  # type: ignore[assignment]

    interval = args.interval if args.interval is not None else config.interval
    if args.json:
        _dump(
            {
                "event": "start",
                "adapter": ctx_stub.adapter.name,
                "portal": ctx_stub.portal.base_url,
                "account": config.account,
                "operator": config.operator,
                "ip": ctx_stub.ip,
                "interval": interval,
                "log": args.log,
            }
        )
    else:
        _startup_summary(config, ctx_stub, interval, args.log)

    def make():
        return build(config).portal

    def report(cycle: Cycle, index: int) -> None:
        stamp = time.strftime("%H:%M:%S")
        took = f"{cycle.elapsed:.1f}s"
        if args.json:
            _dump(
                {
                    "event": "cycle",
                    "t": stamp,
                    "cycle": index,
                    "online": cycle.online,
                    "attempted": cycle.attempted,
                    "ok": cycle.ok,
                    "msg": cycle.message,
                    "elapsed_ms": round(cycle.elapsed * 1000),
                }
            )
        else:
            _say(f"[{stamp}] #{index} {cycle.message}（{took}）")

    try:
        return watch(
            make,
            account=config.account,
            password=config.password,
            operator=config.operator,
            interval=interval,
            jitter=config.jitter,
            probe_host=config.probe_host,
            once=args.once,
            max_cycles=args.cycles,
            on_cycle=report,
        )
    finally:
        if log is not None:
            log.close()
