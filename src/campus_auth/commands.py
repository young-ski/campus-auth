"""各子命令的实现。

`cli.py` 只管解析参数、拼 parser 和收尾；命令之间不互相调用，共用这里的小工具。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import adapters, credentials, net
from . import install as installer
from .config import ENV_PASSWORD, Config, find_config_file, load
from .errors import (
    EXIT_CONFIG,
    EXIT_ENV,
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TRANSPORT,
    CampusAuthError,
    ParseError,
    TransportError,
)
from .keepalive import Cycle, watch
from .logfile import RotatingLog, Tee
from .probe import probe, to_json
from .runner import Context, _host_port, build, require_campus

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
    _say("下一步：填 account，然后存密码 —— `campus-auth password`（交互式，不回显）")
    if not credentials.available():
        _say(f"! 没装 keyring：改用 export ${ENV_PASSWORD}=...，或装 campus-auth[keyring]")
    _say("填完跑 `campus-auth status` 自检：没配好它会直接指出来")
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


def cmd_adapters(_: argparse.Namespace) -> int:
    for name in adapters.names():
        adapter = adapters.get_adapter(name)
        _say(f"{name:10} {adapter.school}  [{adapter.status}]  <{adapter.base_url}>")
        if adapter.notes:
            _say(f"{'':10} {adapter.notes}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    if not config.account:
        _say("! 还没填 account：`campus-auth init` 生成模板，把学号填进去再跑 status。")
        return EXIT_CONFIG
    ctx = build(config, need_password=False)
    require_campus(ctx)
    sessions = ctx.portal.sessions()

    mine = [session for session in sessions if _is_ours(session, ctx)]
    others = [session for session in sessions if session not in mine]

    if args.json:
        _dump(
            {
                "online": bool(mine),
                "ip": ctx.ip,
                "account": config.account,
                "sessions": [{**s.raw, "ours": s in mine} for s in sessions],
            }
        )
        return EXIT_OK if mine else EXIT_REJECTED

    if not sessions:
        _say(f"未在线（本机 {ctx.ip}，{ctx.zone}）")
        _zone_line(ctx)
        return EXIT_REJECTED

    for session in mine:
        account_text = session.account or config.account
        traffic = f"{session.uplink or '?'}/{session.downlink or '?'} B"
        _say(
            f"在线（你）  账号 {account_text}  IP {session.ip}  "
            f"时长 {session.time_long or '?'}s  上行/下行 {traffic}"
        )
    for session in others:
        _say(f"在线（别人）账号 {session.account}  IP {session.ip}  时长 {session.time_long}s")

    if mine:
        return EXIT_OK
    if any(session.ip == ctx.ip for session in sessions):
        _say(
            f"! 本机 IP {ctx.ip} 上有会话，但账号不是 {config.account} —— "
            "可能是上一位用户还没掉线：等它超时，或 `campus-auth unbind` 解绑。"
        )
    else:
        _say(f"! 门户里有人在线，但没有本机 IP {ctx.ip} 的会话 —— 你还没登录。")
    return EXIT_REJECTED


def _is_ours(session, ctx: Context) -> bool:
    """IP 对上、且账号也对上才算“是我们自己的会话”。"""
    if session.ip != ctx.ip:
        return False
    if not session.account:
        return True  # 门户没回账号，只能按 IP 认
    return ctx.config.account in session.account


def cmd_check(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)
    try:
        online = ctx.portal.mine() is not None
    except CampusAuthError as exc:
        return exc.exit_code
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

    if args.show:
        stored = credentials.get(config.adapter, config.account)
        if not stored:
            _say(
                f"{config.adapter}/{config.account} 没有存密码；跑 `campus-auth password` 存一个。"
            )
            return EXIT_REJECTED
        _say(f"钥匙串里有 {config.adapter}/{config.account} 的密码（{len(stored)} 位）。")
        return EXIT_OK

    secret = config.password
    if args.password is None and not args.password_stdin:
        if sys.stdin.isatty():
            try:
                secret = getpass.getpass(f"{config.adapter}/{config.account} 的密码: ")
            except (EOFError, KeyboardInterrupt):
                _say("")
                return EXIT_REJECTED
        else:
            secret = sys.stdin.readline().rstrip("\r\n")
    if not secret:
        _say("没读到密码。")
        return EXIT_CONFIG

    if credentials.set(config.adapter, config.account, secret):
        _say(f"已存入钥匙串 {config.adapter}/{config.account}。")
        return EXIT_OK
    _say('! 钥匙串不可用：先 `pip install "campus-auth[keyring]"`。')
    return EXIT_ENV


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
    ctx = build(config, need_password=False)  # Dr.COM 注销不校验密码
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
    try:
        payload = ctx.portal.unbind()
    except (TransportError, ParseError) as exc:
        # 门户回 HTML（地址写错、改版）时解析不出 JSON，落到这里
        _say(f"解绑失败: {str(exc).splitlines()[0]}")
        hint = ctx.adapter.hint_for(None, str(exc))
        if hint:
            _say(f"! {hint}")
        if args.json:
            _dump({"ok": False, "error": str(exc)})
        return EXIT_TRANSPORT
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

    # discover 要先敲一次门户，离线时可能拿不到
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
    _say("! 快捷方式里的密码是密文，但密钥（IP）就在同一个 URL 里 —— 分享 .url 等于给出密码。")
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
    config.validate(need_password=False)  # 没账号装上也不会成功
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

    installer.check_python(sys.executable)
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
