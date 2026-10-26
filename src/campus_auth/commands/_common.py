"""子命令共用的小工具：输出、配置装配、提示。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..config import Config, load
from ..runner import Context, build, require_campus

CONFIG_TEMPLATE = """\
# campus-auth 配置。密码建议放系统钥匙串（`campus-auth password`），其次环境变量 {env}。
adapter = "{adapter}"
account = ""            # 学号，纯数字，别带 @ 后缀
password = ""
operator = "none"      # none / {operators}
# mac = ""             # 留空自动探测
# ip = ""              # 留空自动探测
# base_url = ""        # 留空用适配层里的地址
verify_tls = false     # 校园门户基本是自签证书
timeout = 20
retries = 2
interval = 120         # watch 模式两轮之间秒数
probe_host = "www.baidu.com"
"""


# ---------- 输出 ----------


def _say(message: str = "") -> None:
    print(message, flush=True)


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)


def _zone_line(ctx: Context) -> None:
    if ctx.zone_hint:
        _say(f"! {ctx.zone_hint}")


def _config(args: argparse.Namespace) -> Config:
    overrides = {
        "adapter": args.adapter,
        "account": args.account,
        "operator": args.operator,
        "mac": args.mac,
        "ip": args.ip,
        "base_url": args.url,
        "timeout": args.timeout,
        "retries": args.retries,
    }
    if args.password_stdin:
        overrides["password"] = sys.stdin.readline().rstrip("\r\n")
    elif args.password is not None:
        overrides["password"] = args.password
    if args.verify_tls:
        overrides["verify_tls"] = True
    if args.show_secrets:
        overrides["mask_urls"] = False
    return load(args.config, overrides)


def _prepare(args: argparse.Namespace, config: Config) -> Context:
    ctx = build(config)
    require_campus(ctx)
    return ctx


def _payload_ok(payload: dict) -> bool:
    """注销/解绑的成败判定：三家门户用的字段各不相同。"""
    if payload.get("result") in (1, "1", True, "success", "ok"):
        return True
    return str(payload.get("error") or "").lower() == "ok"


def _hint_line(ctx, ok: bool, msg: object) -> None:
    """失败时请适配层把含糊报错翻成人话。

    适配层的兜底提示只是把原文再抄一遍，已经在上面打过了 —— 那就别重复。
    """
    if ok:
        return
    text = str(msg or "")
    hint = ctx.adapter.hint_for(None, text)
    if hint and (not text or text not in hint):
        _say(f"! {hint}")
