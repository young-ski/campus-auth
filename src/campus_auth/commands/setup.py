"""`setup`：一条命令把首次配置跑完。

同学手里只会有一份解压出来的目录，不该先读一页文档，也不该被丢进记事本。这里按顺序做完：
问学号 → 问密码 → 写配置 → 当场验一次 → 问要不要开机自启。

所有中文都在 Python 里，不放进 `.cmd` —— cmd.exe 按 OEM 代码页读批处理，UTF-8 的 `echo`
在 cp936 上会变成乱码。
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import re
import sys
import time
from pathlib import Path

from .. import adapters, credentials
from ..config import ENV_PASSWORD, default_config_path, load
from ..errors import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TRANSPORT,
    CampusAuthError,
)
from ..install import adopt_pyz, check_entry, install, running_pyz, service_for
from ..runner import build
from ._common import CONFIG_TEMPLATE, _restrict, _say

ACCOUNT = re.compile(r"\d+")

# 三次都填错：这是配置问题，不是「用户中断」，退出码不同
GAVE_UP = object()


def _toml_str(value: str) -> str:
    """把字符串写成 TOML 基本字符串（密码限定 ASCII，只需管引号和反斜杠）。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _masked(password: str) -> str:
    return f"{password[0]}…{password[-1]}" if len(password) > 4 else "…"


def _read_line(prompt: str) -> str | None:
    """读一行；Ctrl-C / EOF 统一返回 None，由调用方决定怎么收场。"""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        _say("")
        return None


def _ask_account(keep: str = "") -> str | None | object:
    """问学号。只认数字，`0814@cmcc` 这种把后缀也抄进来的会重问一次。"""
    if keep:
        _say("")
        _say(f"沿用上次填的学号 {keep}（想换就重新跑并加 --force）。")
        return keep
    _say("")
    for attempt in range(3):
        raw = _read_line("学号（纯数字）: ")
        if raw is None:
            return None
        account = raw.strip()
        # 手快把后缀抄进来了：后缀由 -w 拼，这里只取前面的数字
        if "@" in account:
            account = account.split("@", 1)[0]
        if account and ACCOUNT.fullmatch(account):
            return account
        if attempt == 0:
            _say("! 学号只填数字。")
    _say("! 三次都没填对，先退出。重新跑 `campus-auth setup` 再来。")
    return GAVE_UP


def _ask_password(account: str) -> str | None:
    """问密码。终端里不回显；管道里读一行。"""
    try:
        if sys.stdin.isatty():
            return getpass.getpass(f"{account} 的密码（输入时不显示）: ")
        _say("（从标准输入读一行密码）")
        return sys.stdin.readline().rstrip("\r\n")
    except (EOFError, KeyboardInterrupt):
        _say("")
        return None


def _write_config(target: Path, adapter_name: str, account: str, password: str) -> None:
    """写配置。密码只在钥匙串用不了时才落盘。"""
    adapter = adapters.get_adapter(adapter_name)
    text = CONFIG_TEMPLATE.format(
        env=ENV_PASSWORD,
        adapter=adapter.name,
        base_url=adapter.base_url,
        operators=" / ".join(adapter.operator_suffixes) or "（无）",
    )
    text = text.replace('account = ""', f"account = {_toml_str(account)}")
    if password:
        # 用函数做替换：re.sub 会把替换串里的 `\` 再吃一遍，`\"` 会退化成 `"`
        text = re.sub(
            r"^password\s*=.*$",
            lambda _m: f"password = {_toml_str(password)}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _restrict(target)


def _verify(config_path: Path, secret: str) -> int:
    """当场验一次：连得上门户、账号密码说得通、在不在线。

    用手里这个密码，不回头查钥匙串 —— 刚存进去不一定立刻读得到。
    """
    _say("")
    config = load(config_path)
    config.password = secret
    try:
        ctx = build(config)
        _say(f"门户 {ctx.portal.base_url}  本机 IP {ctx.ip}")
        if ctx.portal.mine():
            _say("检查结果：已经在线，配置没问题。")
            return EXIT_OK
        _say("当前不在线。现在登录一次试试…")
        result = ctx.portal.login()
        _say(f"服务端: {result.msg or '(无消息)'}  ret_code={result.ret_code}")
        if result.hint:
            _say(f"! {result.hint}")
        for _ in range(3):
            if ctx.portal.mine():
                _say("检查结果：登录成功，已经在线。")
                return EXIT_OK
            time.sleep(0.8)
    except CampusAuthError as exc:
        _say(f"! 检查没通过：{exc}")
        return getattr(exc, "exit_code", EXIT_TRANSPORT)
    _say("检查结果：服务端接了，但没看到自己的会话。先跑 `campus-auth status` 看看。")
    return EXIT_REJECTED


def _ask_autostart(config_path: Path) -> None:
    _say("")
    answer = (_read_line("要装成开机自启吗？断线会自动重连，随时可以卸。[y/N] ") or "").strip()
    if answer.lower() not in {"y", "yes"}:
        _say("没装自启。想装随时跑 `campus-auth install`。")
        return
    try:
        pyz = running_pyz()
        if pyz is not None:
            pyz = adopt_pyz(pyz)
        service = service_for(config_path, pyz=pyz)
        check_entry(sys.executable, pyz)
        install(service)
    except CampusAuthError as exc:
        _say(f"! 自启没装成：{exc}")
        _say("  不影响手动登录；修好后跑 `campus-auth install`。")
        return
    _say("已装成登录自启。")
    for note in service.notes:
        _say(f"· {note}")
    _say("卸载：`campus-auth uninstall`，或在任务管理器「启动」里关掉。")


def cmd_setup(args: argparse.Namespace) -> int:
    adapter_name = args.adapter or "huuc"
    target = Path(args.config) if args.config else default_config_path()
    adapter = adapters.get_adapter(adapter_name)

    _say("campus-auth 首次配置")
    _say("=" * 34)
    _say("先说清楚：这是第三方工具，学校没出过明文规定，用不用你判断，出事自己担。")
    _say("它只做登录/保活，不改计费。密码会进内存、钥匙串或配置文件。")
    _say("")
    _say(f"将使用适配层 {adapter.name}（{adapter.school}），门户 {adapter.base_url}")
    if adapter.name == "huuc":
        _say("这是给河南城建学院的。不是本校就加 `--adapter generic` 重来。")

    if target.exists() and not args.force:
        _say("")
        _say(f"! {target} 已经存在。要重来加 `--force`（会覆盖）。")
        return EXIT_CONFIG

    keep = ""
    if target.exists():
        with contextlib.suppress(CampusAuthError):
            keep = load(target).account.strip()

    account = _ask_account(keep)
    if account is GAVE_UP:
        return EXIT_CONFIG
    if account is None:
        _say("已中断，什么都没改。重新跑 `campus-auth setup` 就行。")
        return EXIT_REJECTED

    secret = _ask_password(account)
    if secret is None:
        _say("已中断，什么都没改。")
        return EXIT_REJECTED
    if not secret:
        _say("! 没读到密码。重跑 `campus-auth setup`，或用 `campus-auth password` 补。")
        return EXIT_CONFIG
    if not secret.isascii():
        _say("! 密码里有非 ASCII 字符，门户前端只按 ASCII 取 charCode，密文会和浏览器不一致。")

    stored = credentials.set(adapter_name, account, secret)
    _write_config(target, adapter_name, account, "" if stored else secret)
    _say("")
    _say(f"配置已写到 {target}")
    if stored:
        _say(f"密码存进了系统钥匙串（{adapter_name}/{account}），配置里不写明文。")
    else:
        _say(f"钥匙串用不了，密码写进了配置文件（{_masked(secret)}，明文，注意别提交）。")

    code = _verify(target, secret)
    _ask_autostart(target)
    _say("")
    _say(f"配置在 {target}；常用命令：`campus-auth status` / `login` / `watch` / `doctor`。")
    _say("出问题先跑 `campus-auth doctor`，把输出发出来（密码不会出现）。")
    return code


__all__ = ["cmd_setup"]
