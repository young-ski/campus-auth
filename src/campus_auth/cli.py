"""命令行入口。

用法速查（完整说明见 README）：

    campus-auth init                 生成配置模板
    campus-auth probe --url URL      先确认门户是不是 Dr.COM
    campus-auth login                登录
    campus-auth status --json        查状态，给脚本用
    campus-auth check                查状态，用退出码表示结果
    campus-auth watch                断线自动重连
    campus-auth urls                 生成 .url / .desktop 快捷方式
    campus-auth install / uninstall  把 watch 装成登录自启 / 卸掉
    campus-auth password             密码存进/删出系统钥匙串
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

from . import __version__, adapters, credentials, net
from . import install as installer
from .config import ENV_PASSWORD, Config, find_config_file, load
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
from .logfile import RotatingLog, Tee
from .probe import probe, to_json
from .runner import Context, _host_port, build, require_campus

CONFIG_TEMPLATE = """\
# campus-auth 配置。密码建议放系统钥匙串（`campus-auth password`），其次环境变量 {env}。
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


def cmd_probe(args: argparse.Namespace) -> int:
    target = args.url or _adapter_base_url(args)
    try:
        analysis, used = probe(target, timeout=args.timeout or 8.0, verify=args.verify_tls)
    except CampusAuthError as exc:
        _err(str(exc))
        _say("")
        _say("提示：探针只从校园网内有效，先连学校 Wi-Fi 再试。")
        return EXIT_ENV

    if args.json:
        _say(to_json(analysis, used))
        return EXIT_OK if analysis.is_drcom else EXIT_REJECTED

    label = {
        "drcom": "是 Dr.COM（eportal）",
        "likely-drcom": "像是 Dr.COM，但证据不全",
        "ruijie": "是锐捷 ePortal，不是 Dr.COM",
        "srun": "是深澜 Srun，不是 Dr.COM",
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
    target_hint = f" --url {used}" if analysis.verdict in {"ruijie", "srun"} else ""
    howto = f"跑不通就照样式改 adapter；先试 `campus-auth login --adapter {{}}{target_hint}`"
    advice = {
        "drcom": "用内置 huuc 当模板起适配层，主要改 base_url、路径和密钥函数。",
        "likely-drcom": "像 Dr.COM 但证据不够，先 F12 抓一次真登录请求再动手。",
        "ruijie": howto.format("ruijie"),
        "srun": howto.format("srun"),
        "unknown": "内置的 huuc / ruijie / srun 都对不上，先确认门户类型。",
    }[analysis.verdict]
    _say(advice)
    if analysis.missing and analysis.is_drcom:
        _say("还缺证据: " + "、".join(analysis.missing[:3]))
    return EXIT_OK if analysis.is_drcom else EXIT_REJECTED


def _adapter_base_url(args: argparse.Namespace) -> str:
    config = load(args.config, {})
    return config.base_url or adapters.get_adapter(config.adapter).base_url


def cmd_adapters(_: argparse.Namespace) -> int:
    for name in adapters.names():
        adapter = adapters.get_adapter(name)
        _say(f"{name:10} {adapter.school}  [{adapter.status}]  <{adapter.base_url}>")
        if adapter.notes:
            _say(f"{'':10} {adapter.notes}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)
    require_campus(ctx)
    sessions = ctx.portal.sessions()
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

    result = ctx.portal.login()
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
    if online and args.remember:
        _remember_password(config)
    return EXIT_OK if online else EXIT_REJECTED


def _remember_password(config: Config) -> None:
    if credentials.set(config.adapter, config.account, config.password):
        _say("已把密码存进系统钥匙串。")
    else:
        _say('! 钥匙串存不进去：先 `pip install "campus-auth[keyring]"`。')


def cmd_password(args: argparse.Namespace) -> int:
    config = _config(args)
    if not config.account:
        _say("缺账号：用 -a 或写进配置，钥匙串是按「适配层/账号」存的。")
        return EXIT_CONFIG

    if args.forget:
        if credentials.delete(config.adapter, config.account):
            _say(f"已从钥匙串删除 {config.adapter}/{config.account}。")
            return EXIT_OK
        _say('! 钥匙串不可用：先 `pip install "campus-auth[keyring]"`。')
        return EXIT_ENV

    if args.password is not None or args.password_stdin:
        if credentials.set(config.adapter, config.account, config.password):
            _say(f"已存入钥匙串 {config.adapter}/{config.account}。")
            return EXIT_OK
        _say('! 钥匙串不可用：先 `pip install "campus-auth[keyring]"`。')
        return EXIT_ENV

    stored = credentials.get(config.adapter, config.account)
    if not stored:
        _say(f"{config.adapter}/{config.account} 没有存密码；给一个（-p 或标准输入）就会存。")
        return EXIT_REJECTED
    _say(f"钥匙串里有 {config.adapter}/{config.account} 的密码（{len(stored)} 位）。")
    return EXIT_OK


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


def cmd_logout(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=adapters.get_adapter(config.adapter).logout_needs_password)
    require_campus(ctx)
    payload = ctx.portal.logout()
    msg = (
        payload.get("msg")
        or payload.get("message")
        or payload.get("suc_msg")
        or payload.get("error")
    )
    _say(f"服务端: {msg or '(无消息)'}")
    ok = _payload_ok(payload)
    _hint_line(ctx, ok, msg)
    if args.json:
        _dump({"ok": ok, "msg": msg})
    return EXIT_OK if ok else EXIT_REJECTED


def cmd_unbind(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)  # 解绑只用学号和 MAC
    require_campus(ctx)
    payload = ctx.portal.unbind()
    message = payload.get("msg") or payload.get("message") or payload.get("error")
    _say(f"服务端: {message or '(无消息)'}  MAC {ctx.mac}")
    ok = _payload_ok(payload)
    _hint_line(ctx, ok, message)
    if args.json:
        _dump({"ok": ok, "msg": message})
    return EXIT_OK if ok else EXIT_REJECTED


def cmd_urls(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)  # 不探活：配合 --ip 可以完全离线生成
    if not config.password:
        _say("! 没给密码，登录快捷方式里的密码字段会是空的")
    if not config.ip and not net.resolves(_host_port(ctx.portal.base_url)[0]):
        _say("! 门户域名解析不了，生成的 URL 要等你回到校园网才有效")

    # 锐捷/深澜要先发现门户地址和 challenge，离线时可能拿不到
    discovered = True
    try:
        ctx.portal.prepare()
    except (CampusAuthError, ValueError) as exc:
        discovered = False
        _say(f"! 发现步骤没跑通（{exc}），只生成门户首页链接")

    targets: list[tuple[str, object]] = []
    if discovered:
        for operator in ["none", *ctx.adapter.operator_suffixes]:
            suffix = "" if operator == "none" else f"({operator})"
            ctx.portal.operator = operator
            targets.append((f"登录{suffix}", ctx.adapter.login_request(ctx.portal)))
        ctx.portal.operator = config.operator
        # 注销和解绑与运营商无关，各来一份就够
        targets.append(("注销", ctx.adapter.logout_request(ctx.portal)))
        targets.append(("解绑", ctx.adapter.unbind_request(ctx.portal)))
    else:
        targets.append(("门户首页", None))

    outdir = Path(args.output or "urls")
    outdir.mkdir(parents=True, exist_ok=True)
    post = False
    for name, request in targets:
        url = ctx.portal.base_url if request is None else ctx.portal.build_url(request)
        if request is not None and request.method.upper() != "GET":
            post = True
        (outdir / f"{name}.url").write_text(
            f"[InternetShortcut]\nURL={url}\n", encoding="ascii", newline="\n"
        )
        if os.name != "nt":
            (outdir / f"{name}.desktop").write_text(
                f"[Desktop Entry]\nType=Link\nName={name}\nURL={url}\n", encoding="utf-8"
            )
    _say(f"写入 {outdir}/: {', '.join(name for name, _ in targets)}")
    if post:
        _say(
            "! 该适配层用 POST 提交，快捷方式只带地址、没有表单体，"
            "点开会是错误页 —— 用 login 命令。"
        )
    _say("注意：URL 里绑着当前 IP 和一次性 challenge，换网段或过期就得重生成。")
    return EXIT_OK


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


def cmd_install(args: argparse.Namespace) -> int:
    config = _config(args)
    path = find_config_file(args.config)
    if path is None:
        _say("! 没找到配置文件：自启要一个真实路径，先 `campus-auth init` 或 --config 指一个")
        return EXIT_CONFIG

    service = installer.service_for(path)
    _say(f"要装的是: {service.kind} → {service.path}")
    if not config.password:
        _say("! 没读到密码：自启不继承当前 shell 的环境变量，先 `campus-auth password` 或写进配置")
    if args.dry_run:
        _say("")
        _say(service.content.rstrip())
        for argv in service.create:
            _say(f"$ {' '.join(argv)}")
        return EXIT_OK

    installer.install(service)
    _say("已安装。")
    for note in service.notes:
        _say(f"· {note}")
    return EXIT_OK


def cmd_uninstall(args: argparse.Namespace) -> int:
    service = installer.service_for(find_config_file(args.config))
    if args.dry_run:
        _say(f"要卸的是: {service.kind} → {service.path}")
        for argv in service.remove:
            _say(f"$ {' '.join(argv)}")
        return EXIT_OK

    installer.uninstall(service)
    _say(f"已卸载（{service.path}）。")
    return EXIT_OK


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
        "check_url": args.check_url,
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
    common.add_argument("--check-url", help="在线判定用的 204 地址（默认 connect.rom.miui.com）")
    common.add_argument("--json", action="store_true", help="输出 JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common], help="生成配置模板")
    init.add_argument("-o", "--output", help="写到哪个文件")
    init.add_argument("-f", "--force", action="store_true", help="覆盖已有文件")
    init.set_defaults(func=cmd_init)

    sub.add_parser("adapters", parents=[common], help="列出内置适配层").set_defaults(
        func=cmd_adapters
    )
    login_p = sub.add_parser("login", parents=[common], help="登录")
    login_p.add_argument("--remember", action="store_true", help="成功后把密码存进系统钥匙串")
    login_p.set_defaults(func=cmd_login)
    sub.add_parser("logout", parents=[common], help="注销").set_defaults(func=cmd_logout)
    sub.add_parser("unbind", parents=[common], help="解除 MAC 绑定").set_defaults(func=cmd_unbind)
    sub.add_parser("status", parents=[common], help="查看在线会话").set_defaults(func=cmd_status)

    check = sub.add_parser("check", parents=[common], help="只查在线状态，用退出码表达")
    check.add_argument("-q", "--quiet", action="store_true")
    check.set_defaults(func=cmd_check)

    probe_p = sub.add_parser(
        "probe", parents=[common], help="探测门户是不是 Dr.COM（--url 给地址）"
    )
    probe_p.set_defaults(func=cmd_probe)

    urls = sub.add_parser("urls", parents=[common], help="为当前 IP 生成快捷方式")
    urls.add_argument("-o", "--output", help="输出目录")
    urls.set_defaults(func=cmd_urls)

    watch_p = sub.add_parser("watch", parents=[common], help="断线自动重连")
    watch_p.add_argument("--once", action="store_true", help="只跑一轮")
    watch_p.add_argument("--cycles", type=int, help="跑多少轮后退出")
    watch_p.add_argument("--interval", type=float, help="两轮间隔秒数")
    watch_p.add_argument("--log", help="同时写进这个文件（按 1 MiB 轮转，留一份 .1）")
    watch_p.set_defaults(func=cmd_watch)

    password_p = sub.add_parser("password", parents=[common], help="把密码存进/删出系统钥匙串")
    password_p.add_argument("--forget", action="store_true", help="删掉存着的密码")
    password_p.set_defaults(func=cmd_password)

    install_p = sub.add_parser(
        "install", parents=[common], help="把 watch 装成登录自启（计划任务 / systemd / launchd）"
    )
    install_p.add_argument("--dry-run", action="store_true", help="只打印要写什么、跑什么")
    install_p.set_defaults(func=cmd_install)

    uninstall_p = sub.add_parser("uninstall", parents=[common], help="卸掉 install 装的自启")
    uninstall_p.add_argument("--dry-run", action="store_true", help="只打印要跑什么")
    uninstall_p.set_defaults(func=cmd_uninstall)
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
