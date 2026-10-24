"""命令行入口。

用法速查（完整说明见 README）：

    campus-auth init                 生成配置模板
    campus-auth login                登录
    campus-auth status --json        查状态，给脚本用
    campus-auth check                查状态，用退出码表示结果
    campus-auth watch                断线自动重连
    campus-auth urls                 生成 .url / .desktop 快捷方式
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from . import __version__, adapters, net
from .config import ENV_PASSWORD, Config, load
from .errors import (
    EXIT_CONFIG,
    EXIT_ENV,
    EXIT_OK,
    EXIT_REJECTED,
    CampusAuthError,
    ConfigError,
    EnvironmentError_,
)
from .keepalive import Cycle, watch
from .runner import Context, _host_port, build, require_campus

CONFIG_TEMPLATE = """\
# campus-auth 配置。密码建议走环境变量 {env}，别提交这一行。
adapter = "{adapter}"
account = "你的学号"
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


# ---------- 子命令 ----------


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.output or args.config or "campus-auth.toml")
    if target.exists() and not args.force:
        _err(f"{target} 已存在，加 --force 覆盖")
        return EXIT_CONFIG
    adapter = adapters.get_adapter(args.adapter or "huuc")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        CONFIG_TEMPLATE.format(
            env=ENV_PASSWORD,
            adapter=adapter.name,
            operators=" / ".join(adapter.operator_suffixes) or "（本适配层无）",
        ),
        encoding="utf-8",
    )
    _say(f"已写入 {target}")
    _say(f"下一步：填 account，导出 ${ENV_PASSWORD}，然后 `campus-auth status`")
    return EXIT_OK


def cmd_adapters(_: argparse.Namespace) -> int:
    for name in adapters.names():
        adapter = adapters.get_adapter(name)
        _say(f"{name:10} {adapter.school}  <{adapter.base_url}>")
        if adapter.notes:
            _say(f"{'':10} {adapter.notes}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)
    require_campus(ctx)
    sessions = ctx.portal.online()
    if args.json:
        _dump({"online": bool(sessions), "ip": ctx.ip, "sessions": [s.raw for s in sessions]})
        return EXIT_OK if sessions else EXIT_REJECTED
    if not sessions:
        _say(f"未在线（本机 {ctx.ip}，{ctx.zone}）")
        _zone_line(ctx)
        return EXIT_REJECTED
    for session in sessions:
        _say(
            f"在线  账号 {session.account}  IP {session.ip}  时长 {session.time_long}s  "
            f"上行/下行 {session.uplink}/{session.downlink} B"
        )
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)
    try:
        online = ctx.portal.mine() is not None
    except CampusAuthError:
        return EXIT_ENV
    if args.quiet:
        return EXIT_OK if online else EXIT_REJECTED
    _say("online" if online else "offline")
    return EXIT_OK if online else EXIT_REJECTED


def cmd_login(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = _prepare(args, config)
    account = ctx.adapter.format_account(config.account, config.operator)
    _say(f"IP {ctx.ip}  MAC {ctx.mac or '(空)'}  账号 {account}")
    _zone_line(ctx)

    if ctx.portal.mine():
        _say("已经在线，无需重复登录")
        return EXIT_OK

    result = ctx.portal.login(config.account, config.password, config.operator)
    _say(f"服务端: {result.msg or '(无消息)'}  ret_code={result.ret_code}")
    if result.hint:
        _say(f"! {result.hint}")

    online = False
    for attempt in range(3):
        try:
            if ctx.portal.mine():
                online = True
                break
        except CampusAuthError:
            pass
        time.sleep(0.8 * (attempt + 1))

    if args.json:
        _dump(
            {
                "ok": online,
                "result": result.ok,
                "msg": result.msg,
                "ret_code": result.ret_code,
                "hint": result.hint,
                "ip": ctx.ip,
            }
        )
    _say("结果: 已在线" if online else "结果: 未确认在线")
    return EXIT_OK if online else EXIT_REJECTED


def cmd_logout(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = _prepare(args, config)
    payload = ctx.portal.logout()
    _say(f"服务端: {payload.get('msg') or '(无消息)'}")
    ok = bool(payload.get("result"))
    if args.json:
        _dump({"ok": ok, "msg": payload.get("msg")})
    return EXIT_OK if ok else EXIT_REJECTED


def cmd_unbind(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = _prepare(args, config)
    payload = ctx.portal.unbind(config.account)
    _say(f"服务端: {payload.get('msg') or '(无消息)'}  MAC {ctx.mac}")
    ok = bool(payload.get("result"))
    if args.json:
        _dump({"ok": ok, "msg": payload.get("msg")})
    return EXIT_OK if ok else EXIT_REJECTED


def cmd_urls(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config)  # 不探活：配合 --ip 可以完全离线生成
    if not config.ip and not net.resolves(_host_port(ctx.portal.base_url)[0]):
        _say("! 门户域名解析不了，生成的 URL 要等你回到校园网才有效")

    targets: list[tuple[str, str, list]] = []
    for operator in ["none", *ctx.adapter.operator_suffixes]:
        suffix = "" if operator == "none" else f"({operator})"
        targets.append(
            (
                f"登录{suffix}",
                ctx.adapter.login_path,
                ctx.adapter.login_params(
                    ip=ctx.ip,
                    mac=ctx.mac,
                    account=config.account,
                    password=config.password,
                    operator=operator,
                ),
            )
        )
    # 注销和解绑与运营商无关，各来一份就够
    targets.append(
        ("注销", ctx.adapter.logout_path, ctx.adapter.logout_params(ip=ctx.ip, mac=ctx.mac))
    )
    targets.append(
        (
            "解绑",
            ctx.adapter.unbind_path,
            ctx.adapter.unbind_params(ip=ctx.ip, mac=ctx.mac, account=config.account),
        )
    )

    outdir = Path(args.output or "urls")
    outdir.mkdir(parents=True, exist_ok=True)
    for name, path, params in targets:
        url = ctx.portal.build_url(path, params)
        (outdir / f"{name}.url").write_text(
            f"[InternetShortcut]\nURL={url}\n", encoding="ascii", newline="\n"
        )
        if os.name != "nt":
            (outdir / f"{name}.desktop").write_text(
                f"[Desktop Entry]\nType=Link\nName={name}\nURL={url}\n", encoding="utf-8"
            )
    _say(f"写入 {outdir}/: {', '.join(name for name, _, _ in targets)}")
    _say("注意：URL 里绑着当前 IP 派生的密钥，换网段就得重生成。")
    return EXIT_OK


def cmd_watch(args: argparse.Namespace) -> int:
    config = _config(args)
    build(config)  # 提前校验配置，失败就别进循环了

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


# ---------- 装配 ----------


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
    return load(args.config, overrides)


def _prepare(args: argparse.Namespace, config: Config) -> Context:
    ctx = build(config)
    require_campus(ctx)
    return ctx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="campus-auth",
        description="Dr.COM / eportal 校园网门户认证客户端",
        epilog="适配层用 --adapter 选，内置: " + ", ".join(adapters.names()),
    )
    parser.add_argument("--version", action="version", version=f"campus-auth {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="配置文件路径")
    common.add_argument("--adapter", help="适配层名，或 module:attr")
    common.add_argument("-a", "--account", help="学号（纯数字，不带 @ 后缀）")
    common.add_argument("-w", "--operator", help="运营商 none/cmcc/unicom/dx")
    common.add_argument("-p", "--password", help="密码（不推荐，会留在历史里）")
    common.add_argument("--password-stdin", action="store_true", help="从标准输入读密码")
    common.add_argument("--mac", help="覆盖 MAC（12 位十六进制）")
    common.add_argument("--ip", help="覆盖本机 IP（离线生成 URL 时用）")
    common.add_argument("--url", help="覆盖门户地址")
    common.add_argument("--timeout", type=float, help="单次请求超时秒数")
    common.add_argument("--retries", type=int, help="传输重试次数")
    common.add_argument("--verify-tls", action="store_true", help="校验证书")
    common.add_argument("--json", action="store_true", help="输出 JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common], help="生成配置模板")
    init.add_argument("-o", "--output", help="写到哪个文件")
    init.add_argument("-f", "--force", action="store_true", help="覆盖已有文件")
    init.set_defaults(func=cmd_init)

    sub.add_parser("adapters", parents=[common], help="列出内置适配层").set_defaults(
        func=cmd_adapters
    )
    sub.add_parser("login", parents=[common], help="登录").set_defaults(func=cmd_login)
    sub.add_parser("logout", parents=[common], help="注销").set_defaults(func=cmd_logout)
    sub.add_parser("unbind", parents=[common], help="解除 MAC 绑定").set_defaults(func=cmd_unbind)
    sub.add_parser("status", parents=[common], help="查看在线会话").set_defaults(func=cmd_status)

    check = sub.add_parser("check", parents=[common], help="只查在线状态，用退出码表达")
    check.add_argument("-q", "--quiet", action="store_true")
    check.set_defaults(func=cmd_check)

    urls = sub.add_parser("urls", parents=[common], help="为当前 IP 生成快捷方式")
    urls.add_argument("-o", "--output", help="输出目录")
    urls.set_defaults(func=cmd_urls)

    watch_p = sub.add_parser("watch", parents=[common], help="断线自动重连")
    watch_p.add_argument("--once", action="store_true", help="只跑一轮")
    watch_p.add_argument("--cycles", type=int, help="跑多少轮后退出")
    watch_p.add_argument("--interval", type=float, help="两轮间隔秒数")
    watch_p.set_defaults(func=cmd_watch)
    return parser


def _force_utf8() -> None:
    """重定向到文件/管道时也保证输出是 UTF-8，别变成 GBK 乱码。"""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        _err(f"配置: {exc}")
        return EXIT_CONFIG
    except EnvironmentError_ as exc:
        _err(f"环境: {exc}")
        return EXIT_ENV
    except CampusAuthError as exc:
        _err(str(exc))
        if args.json:
            _dump({"ok": False, "error": str(exc)})
        return exc.exit_code
    except KeyboardInterrupt:
        _err("已中断")
        return 130
    except Exception as exc:  # 未预期的错误给 traceback，别静默
        _err(f"意外错误: {exc!r}")
        traceback.print_exc()
        return 70


if __name__ == "__main__":
    sys.exit(main())
