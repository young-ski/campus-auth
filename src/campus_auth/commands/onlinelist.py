"""onlinelist：扫网段，把门户里的在线会话一次性列出来。

门户的 `online_list` 一次只答一个 IP，所以「所有人的名单」= 按网段逐个地址问。
默认网段写在适配层里（`scan_ranges`），也可以 `--range` 临时指定。`-e` 导出
CSV；`--json` 给脚本读。
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from pathlib import Path

from ..errors import EXIT_OK, EXIT_TRANSPORT, ConfigError
from ..onlinelist import parse_targets, scan
from ..portal import Session
from ..runner import build, require_campus
from ._common import _config, _dump, _err, _note, _restrict, _say


def _duration(seconds: str) -> str:
    total = _seconds(seconds)
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m" if minutes else f"{total}s"


def _seconds(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _table(sessions: list[Session], ours: str) -> str:
    """固定的列宽，别为了对齐把一整行读成好几段。"""
    rows = [
        ("IP", "账号", "上线时间", "已在线", "本机"),
        *[
            (
                session.ip,
                session.account or "(门户没回)",
                _since(session),
                _duration(session.time_long),
                "*" if session.ip == ours else "",
            )
            for session in sessions
        ],
    ]
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)


def _since(session: Session) -> str:
    """`online_time` 是门户给的「上线于」，格式化不了就原样。"""
    value = session.raw.get("online_time")
    return str(value)[:19] if value else "?"


def _csv_text(sessions: list[Session], ours: str) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("IP", "账号", "MAC", "上线时间", "在线秒数", "本机"))
    for session in sessions:
        writer.writerow(
            (
                session.ip,
                session.account,
                session.mac,
                _since(session),
                session.time_long,
                "1" if session.ip == ours else "0",
            )
        )
    return buffer.getvalue()


def _write_csv(path: str, sessions: list[Session], ours: str) -> None:
    text = _csv_text(sessions, ours)
    if path == "-":
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    target = Path(path)
    try:
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            handle.write(text)
    except OSError as exc:
        raise ConfigError(f"写不了 CSV {target}: {exc}") from exc
    _restrict(target)
    _err(f"CSV 已写到 {target}（{len(sessions)} 行）")


def _targets(args: argparse.Namespace, adapter) -> list[str]:
    specs = list(args.range or [])
    zones = list(getattr(args, "zones", None) or [])
    if zones:
        unknown = [zone for zone in zones if zone not in adapter.scan_zones]
        if unknown:
            known = "、".join(f"-{zone}" for zone in adapter.scan_zones) or "（适配层没有区域参数）"
            raise ConfigError(
                f"适配层 {adapter.name} 不认识区域 {'、'.join(unknown)}；可用: {known}"
            )
        for zone in zones:
            specs.extend(adapter.scan_zones[zone])
    if not specs:
        specs = list(adapter.scan_ranges)
    if not specs:
        raise ConfigError(
            f"适配层 {adapter.name} 没写默认网段：用 -jxl 这类区域参数或 --range 指定，"
            "比如 --range 10.152.0.0/16 或 --range 10.152.59.*"
        )
    return parse_targets(specs)


def _progress(enabled: bool):
    if not enabled:
        return None
    started = time.monotonic()

    def report(done: int, total: int, hits: int) -> None:
        elapsed = time.monotonic() - started
        _err(f"已扫 {done}/{total}，命中 {hits}，{elapsed:.0f}s")

    return report


def _dedupe(sessions: list[Session]) -> list[Session]:
    """重试可能把同一行拿回来两次（上次超时但服务端其实答了），按内容去重。"""
    seen: set[tuple[str, ...]] = set()
    unique: list[Session] = []
    for session in sessions:
        key = (
            session.ip,
            session.account,
            session.mac,
            session.time_long,
            str(session.raw.get("online_time") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(session)
    return unique


def cmd_onlinelist(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False, need_account=False)
    require_campus(ctx)

    if args.export == "-" and args.json:
        raise ConfigError("`-e -` 和 `--json` 都占 stdout，二选一")
    targets = _targets(args, ctx.adapter)
    if not targets:
        raise ConfigError("网段展开后是空的")
    timeout = args.timeout or min(config.timeout, 8.0)
    spec = f"扫 {len(targets)} 个地址（{ctx.adapter.name}），并发 {args.workers}"
    if args.zones:
        spec += f"，区域 {'、'.join(args.zones)}"
    if args.export == "-":
        _err(spec)
    else:
        _note(args, spec)

    rounds = max(0, args.retry) + 1
    retry_workers = min(args.workers, 12)
    covered = 0
    retried = 0
    failed_ips: list[str] = []
    collected: list[Session] = []
    pending = targets
    cancelled = False
    started = time.monotonic()
    for attempt in range(1, rounds + 1):
        # 重试时把并发压下来：队列一散，刚才超时的地址往往几十毫秒就答了
        workers = args.workers if attempt == 1 else retry_workers
        outcome = scan(
            ctx.portal,
            ctx.adapter,
            pending,
            workers=workers,
            timeout=timeout,
            progress=_progress(attempt == 1 and not args.quiet and not args.json),
        )
        if attempt == 1:
            covered = outcome.scanned
        collected.extend(outcome.sessions)
        failed_ips = outcome.failed_ips
        cancelled = outcome.cancelled
        if cancelled or not failed_ips:
            break
        if attempt < rounds:
            retried += len(failed_ips)
            _err(f"第 {attempt} 轮有 {len(failed_ips)} 个地址失败，降并发 {retry_workers} 重试…")
            pending = failed_ips
    elapsed = time.monotonic() - started
    sessions = _dedupe(collected)
    if cancelled:
        _err(f"已中断：扫了 {covered}/{len(targets)}，结果照常输出")

    all_failed = bool(covered) and len(failed_ips) >= covered
    ours = ctx.ip
    if args.export:
        _write_csv(args.export, sessions, ours)

    if args.json:
        _dump(
            {
                "ok": not all_failed,
                "scanned": covered,
                "failed": len(failed_ips),
                "failed_ips": failed_ips,
                "retried": retried,
                "cancelled": cancelled,
                "ranges": targets,
                "sessions": [
                    {
                        "ip": session.ip,
                        "account": session.account,
                        "mac": session.mac,
                        "online_since": _since(session),
                        "seconds": _seconds(session.time_long),
                        "ours": session.ip == ours,
                    }
                    for session in sessions
                ],
            }
        )
    elif args.export != "-":
        _say(_table(sessions, ours))

    _err(
        f"扫完 {covered} 个地址，用时 {elapsed:.1f}s，"
        f"命中 {len(sessions)} 条，重试 {retried} 次，最终失败 {len(failed_ips)} 个"
    )
    if all_failed:
        _err("所有地址都失败了：多半不在校园网，或门户地址不对")
        return EXIT_TRANSPORT
    if cancelled:
        return 130
    return EXIT_OK
