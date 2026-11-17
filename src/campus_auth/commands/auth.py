"""登录态相关的子命令：status / check / login / logout / unbind。"""

from __future__ import annotations

import argparse
import time

from ..errors import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TRANSPORT,
    CampusAuthError,
    ParseError,
    TransportError,
)
from ..runner import Context, build, require_campus
from ._common import (
    _config,
    _dump,
    _hint_line,
    _note,
    _payload_ok,
    _prepare,
    _say,
    _zone_line,
)


def _is_ours(session, ctx: Context) -> bool:
    """IP 对上、且账号也对上才算“是我们自己的会话”。"""
    if session.ip != ctx.ip:
        return False
    if not session.account:
        return True  # 门户没回账号，只能按 IP 认
    return ctx.config.account in session.account


def _on_this_machine(session, ctx: Context) -> bool:
    """会话是不是挂在这台机器上：先比 IP；门户回得出 MAC 时再核一遍。

    共用网段里 DHCP 会把 IP 转手，只比 IP 会把上一位用户的会话认成这台机器的。
    """
    if session.ip != ctx.ip:
        return False
    remote = session.mac.upper().replace(":", "").replace("-", "")
    return not (ctx.mac and remote and remote != ctx.mac)


def cmd_whoami(args: argparse.Namespace) -> int:
    """这台机器现在登的是哪个账号：只读会话列表，不碰密码、也不用先填 account。"""
    config = _config(args)
    ctx = build(config, need_password=False, need_account=False)
    require_campus(ctx)
    sessions = ctx.portal.sessions()

    hits = [session for session in sessions if _on_this_machine(session, ctx)]
    accounts = [session.account for session in hits if session.account]
    configured = config.account
    # 门户没回账号（或本机压根没配）时说不清，别硬报「不一致」
    matches = (
        None
        if not configured or not accounts
        else all(configured in account for account in accounts)
    )

    if args.json:
        _dump(
            {
                "ok": bool(hits),
                "found": bool(hits),
                "ip": ctx.ip,
                "mac": ctx.mac,
                "account": accounts[0] if accounts else "",
                "accounts": accounts,
                "matches_config": matches,
            }
        )
        return EXIT_OK if hits else EXIT_REJECTED

    if not hits:
        _say(f"本机 {ctx.ip} 上没有会话（{ctx.zone}）")
        if configured:
            _say(f"配置里的账号 {configured} 现在不在线。")
        _zone_line(ctx, args)
        return EXIT_REJECTED

    for session in hits:
        elapsed = f"  时长 {session.time_long}s" if session.time_long else ""
        _say(f"本机 {ctx.ip}  账号 {session.account or '(门户没回账号)'}{elapsed}")
    if matches is False:
        _say(
            f"! 不是配置里的 {configured}：可能上一位用户还没掉线，或这台机器换了号 ——"
            " 登录会顶掉它。"
        )
    elif matches:
        _say("和配置里的账号一致。")
    _say("账号来自门户的会话列表，不是本机记录。")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    if not config.account:
        message = (
            "还没填 account：`campus-auth init` 生成模板，把学号填进去再跑 status"
            "；只想看这台机器现在挂的是谁的号，用 `campus-auth whoami`"
        )
        _note(args, f"! {message}")
        if args.json:
            _dump({"ok": False, "error": message})
        return EXIT_CONFIG
    ctx = build(config, need_password=False)
    require_campus(ctx)
    sessions = ctx.portal.sessions()

    mine = [session for session in sessions if _is_ours(session, ctx)]
    others = [session for session in sessions if session not in mine]

    if args.json:
        _dump(
            {
                "online": bool(mine),  # 你自己的会话（1.0 起）
                "any_online": bool(sessions),  # 门户里任何会话，含别人的
                "ip": ctx.ip,
                "account": config.account,
                "sessions": [{**s.raw, "ours": s in mine} for s in sessions],
            }
        )
        return EXIT_OK if mine else EXIT_REJECTED

    if not sessions:
        _say(f"未在线（本机 {ctx.ip}，{ctx.zone}）")
        _zone_line(ctx, args)
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


def cmd_check(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)
    try:
        online = ctx.portal.mine() is not None
    except CampusAuthError as exc:
        if args.json:
            _dump({"ok": False, "online": False, "error": str(exc)})
        return exc.exit_code
    if args.json:
        _dump({"ok": online, "online": online})
        return EXIT_OK if online else EXIT_REJECTED
    if args.quiet:
        return EXIT_OK if online else EXIT_REJECTED
    _say("online" if online else "offline")
    return EXIT_OK if online else EXIT_REJECTED


from .account import _remember_password  # noqa: E402


def cmd_login(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = _prepare(args, config)
    account = ctx.adapter.format_account(config.account, config.operator)
    _note(args, f"IP {ctx.ip}  MAC {ctx.mac or '(空)'}  账号 {account}")
    _zone_line(ctx, args)

    if ctx.portal.mine():
        _note(args, "已经在线，无需重复登录")
        if args.json:
            _dump(
                {
                    "ok": True,
                    "already_online": True,
                    "result": True,
                    "msg": "已经在线",
                    "ret_code": 0,
                    "hint": "",
                    "ip": ctx.ip,
                }
            )
        return EXIT_OK

    result = ctx.portal.login()
    _note(args, f"服务端: {result.msg or '(无消息)'}  ret_code={result.ret_code}")
    if result.hint:
        _note(args, f"! {result.hint}")

    online = False
    # 被拒时服务端已经给了结论，再轮询 3 次只是白等（真实门户上要 5 秒起）
    attempts = 3 if result.ok else 1
    for attempt in range(attempts):
        try:
            if ctx.portal.mine():
                online = True
                break
        except CampusAuthError:
            pass
        if attempt < attempts - 1:
            time.sleep(0.8 * (attempt + 1))

    _note(args, "结果: 已在线" if online else "结果: 未确认在线")
    if args.json:
        _dump(
            {
                "ok": online,
                "already_online": False,
                "result": result.ok,
                "msg": result.msg,
                "ret_code": result.ret_code,
                "hint": result.hint,
                "ip": ctx.ip,
            }
        )
    if online and args.remember:
        _remember_password(config)
    return EXIT_OK if online else EXIT_REJECTED


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
    _note(args, f"服务端: {msg or '(无消息)'}")
    ok = _payload_ok(payload)
    _hint_line(ctx, ok, msg, args)
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
        _note(args, f"解绑失败: {str(exc).splitlines()[0]}")
        hint = ctx.adapter.hint_for(None, str(exc))
        if hint:
            _note(args, f"! {hint}")
        if args.json:
            _dump({"ok": False, "error": str(exc)})
        return EXIT_TRANSPORT
    message = payload.get("msg") or payload.get("message") or payload.get("error")
    _note(args, f"服务端: {message or '(无消息)'}  MAC {ctx.mac}")
    ok = _payload_ok(payload)
    _hint_line(ctx, ok, message, args)
    if args.json:
        _dump({"ok": ok, "msg": message})
    return EXIT_OK if ok else EXIT_REJECTED
