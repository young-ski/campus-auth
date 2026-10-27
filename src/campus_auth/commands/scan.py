"""probe：先认门户再谈别的。"""

from __future__ import annotations

import argparse

from .. import adapters
from ..config import load
from ..errors import EXIT_OK, EXIT_REJECTED, CampusAuthError, ConfigError
from ..probe import probe, to_json
from ._common import _dump, _err, _say


def _fail(args: argparse.Namespace, exc: CampusAuthError, hint: str) -> int:
    """失败出口：人话进 stderr，`--json` 时 stdout 补一个对象。"""
    _err(str(exc))
    if args.json:
        _dump({"ok": False, "error": str(exc)})
    else:
        _say("")
        _say(hint)
    return exc.exit_code


def cmd_probe(args: argparse.Namespace) -> int:
    target = args.url or _adapter_base_url(args)
    try:
        analysis, used = probe(
            target,
            timeout=args.timeout or 8.0,
            verify=args.verify_tls,
            follow=not args.no_follow,
        )
    except ConfigError as exc:
        # 地址写错是配置问题，别让人去查 Wi-Fi
        return _fail(args, exc, "提示：地址要写成 http(s)://host[:port]，指到 eportal 入口。")
    except CampusAuthError as exc:
        return _fail(args, exc, "提示：探针只从校园网内有效，先连学校 Wi-Fi 再试。")

    if args.json:
        _say(to_json(analysis, used))
        return EXIT_OK if analysis.is_drcom else EXIT_REJECTED

    label = {
        "drcom": "是 Dr.COM（eportal）",
        "likely-drcom": "像是 Dr.COM，但证据不全",
        "ruijie": "是锐捷 ePortal（本项目暂不支持）",
        "srun": "是深澜 Srun（本项目暂不支持）",
        "unknown": "没认出来",
    }[analysis.verdict]
    _say(f"目标 {used}")
    _say(f"判定: {label}   置信度: {analysis.confidence}（{analysis.score} 分）")
    if analysis.evidence:
        _say("")
        for signal in analysis.evidence:
            _say(f"  {'✓' if signal.hit else '·'} {signal.name} (+{signal.weight})")
    for note in analysis.notes:
        _say(f"! {note}")
    _say("")
    advice = {
        "drcom": "照 CONTRIBUTING 抄一份 generic 适配层，主要改 base_url、路径和密钥函数。",
        "likely-drcom": "像 Dr.COM 但证据不够，先 F12 抓一次真登录请求再动手。",
        "ruijie": "锐捷不在本项目范围内：换别的工具，或按 CONTRIBUTING 另写适配层。",
        "srun": "深澜不在本项目范围内：换别的工具，或按 CONTRIBUTING 另写适配层。",
        "unknown": "内置的 huuc / generic 都对不上，先确认门户类型（路由器页、802.1X 也长这样）。",
    }[analysis.verdict]
    _say(advice)
    if analysis.missing and analysis.is_drcom:
        _say("还缺证据: " + "、".join(analysis.missing[:3]))
    return EXIT_OK if analysis.is_drcom else EXIT_REJECTED


def _adapter_base_url(args: argparse.Namespace) -> str:
    config = load(args.config, {})
    return config.base_url or adapters.get_adapter(config.adapter).base_url
