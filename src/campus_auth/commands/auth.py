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
from ._common import _config, _dump, _hint_line, _payload_ok, _prepare, _say, _zone_line


def _is_ours(session, ctx: Context) -> bool:
    """IP 对上、且账号也对上才算“是我们自己的会话”。"""
    if session.ip != ctx.ip:
        return False
    if not session.account:
        return True  # 门户没回账号，只能按 IP 认
    return ctx.config.account in session.account


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    if not config.account:
        message = "还没填 account：`campus-auth init` 生成模板，把学号填进去再跑 status"
        if args.json:
            _dump({"ok": False, "error": message})
        else:
            _say(f"! {message}")
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


from .account import _remember_password  # noqa: E402


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
