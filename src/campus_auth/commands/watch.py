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


def cmd_watch(args: argparse.Namespace) -> int:
    config = _config(args)
    build(config)  # 提前校验配置，失败就别进循环了

    log = None
    if args.log:
        log = RotatingLog(Path(args.log))
        sys.stdout = Tee(sys.stdout, log)  # type: ignore[assignment]
        sys.stderr = Tee(sys.stderr, log)  # type: ignore[assignment]

    def make():
        return build(config).portal

    def report(cycle: Cycle, index: int) -> None:
        stamp = time.strftime("%H:%M:%S")
        if args.json:
            _dump(
                {
                    "t": stamp,
                    "cycle": index,
                    "online": cycle.online,
                    "attempted": cycle.attempted,
                    "ok": cycle.ok,
                    "msg": cycle.message,
                }
            )
        else:
            _say(f"[{stamp}] #{index} {cycle.message}")

    try:
        return watch(
            make,
            account=config.account,
            password=config.password,
            operator=config.operator,
            interval=args.interval if args.interval is not None else config.interval,
            jitter=config.jitter,
            probe_host=config.probe_host,
            once=args.once,
            max_cycles=args.cycles,
            on_cycle=report,
        )
    finally:
        if log is not None:
            log.close()
