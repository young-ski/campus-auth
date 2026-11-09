"""`setup`：一条命令把首次配置跑完。

同学手里只会有一份解压出来的目录，不该先读一页文档。这里按顺序做完：写配置 → 让人填学号 →
存密码（进钥匙串，进不去就写进配置）→ 当场验一次 → 问要不要开机自启。

所有中文都在 Python 里，不放进 `.cmd` —— cmd.exe 按 OEM 代码页读批处理，UTF-8 的 `echo`
在 cp936 上会变成乱码。
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import re
import subprocess
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
from ..install import check_python, install, service_for
from ..runner import build
from ._common import CONFIG_TEMPLATE, _restrict, _say

ACCOUNT = re.compile(r"\d+")


def _open_in_editor(path: Path) -> bool:
    """用默认程序打开配置；打不开就让人自己去看。"""
    if os.name == "nt":
        with contextlib.suppress(OSError):
            os.startfile(path)  # type: ignore[attr-defined]
            return True
    for argv in (["xdg-open", str(path)], ["open", str(path)], ["notepad", str(path)]):
        try:
            subprocess.run(argv, check=False)
        except OSError:
            continue
        return True
    return False


def _toml_str(value: str) -> str:
    """把字符串写成 TOML 基本字符串（密码限定 ASCII，只需管引号和反斜杠）。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _masked(password: str) -> str:
    return f"{password[0]}…{password[-1]}" if len(password) > 4 else "…"


def _ask_account(config_path: Path, adapter_name: str, keep_account: str = "") -> int:
    """写模板、等同学填学号、回来校验。返回退出码（0 表示继续）。

    已经有学号（重跑）时不重复问，也不打开编辑器 —— 非交互跑也不会卡住。
    """
    template = CONFIG_TEMPLATE.format(
        env=ENV_PASSWORD,
        adapter=adapter_name,
        base_url=adapters.get_adapter(adapter_name).base_url,
        operators=" / ".join(adapters.get_adapter(adapter_name).operator_suffixes) or "（无）",
    )
    if keep_account:
        template = template.replace('account = ""', f'account = "{keep_account}"')
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(template, encoding="utf-8")
    _restrict(config_path)

    if not config_path.exists() or not keep_account:
        pass  # 下面统一走编辑流程
    else:
        _say("")
        _say(f"配置已写到 {config_path}，沿用原来的学号 {keep_account}。")
        _say("想改学号就打开它改 account 那一行。")
        return EXIT_OK

    _say("")
    _say(f"配置已写到 {config_path}")
    _say("接下来会打开它，请把 account 那一行的引号里填上学号（纯数字，别带 @ 后缀）。")
    _say("别的行先不用动。")
    if not _open_in_editor(config_path):
        _say("! 没能自动打开，请自己用记事本打开上面的路径。")
    try:
        input("\n填好并保存后，回到这里按回车继续…")
    except (EOFError, KeyboardInterrupt):
        _say("")
        _say("已中断。填好之后可以重新跑 `campus-auth setup`，或直接 `campus-auth status`。")
        return EXIT_REJECTED
    _say("")  # input() 的提示不带换行，后面的消息会黏在同一行
    if not config_path.exists():
        _say(f"! {config_path} 不见了。跑 `campus-auth setup` 重来。")
        return EXIT_CONFIG
    try:
        config = load(config_path)
    except CampusAuthError as exc:
        _say(f"! 配置文件读不了：{exc}")
        return EXIT_CONFIG

    account = config.account.strip()
    if not account:
        _say("! account 还是空的。填好再跑 `campus-auth setup`。")
        return EXIT_CONFIG
    if not ACCOUNT.fullmatch(account):
        _say(f"! 学号看着不对：{account!r}。这里只填数字，别带 @cmcc 这种后缀（后缀由 -w 管）。")
        return EXIT_CONFIG
    return EXIT_OK


def _save_password(config_path: Path, account: str, adapter_name: str) -> tuple[int, str]:
    """取密码并落位：优先钥匙串，进不去就写进配置文件。返回 (退出码, 密码)。"""
    _say("")
    try:
        if sys.stdin.isatty():
            secret = getpass.getpass(f"{account} 的密码（输入时不显示）: ")
        else:
            _say("（从标准输入读一行密码）")
            secret = sys.stdin.readline().rstrip("\r\n")
    except (EOFError, KeyboardInterrupt):
        _say("")
        _say("已中断；还没存密码，稍后跑 `campus-auth password` 补上。")
        return EXIT_REJECTED, ""

    if not secret:
        _say("! 没读到密码；稍后跑 `campus-auth password` 补上。")
        return EXIT_CONFIG, ""
    if not secret.isascii():
        _say("! 密码里有非 ASCII 字符，门户前端只按 ASCII 取 charCode，密文会和浏览器不一致。")

    if credentials.set(adapter_name, account, secret):
        _say(f"密码已存进系统钥匙串（{adapter_name}/{account}），配置里不用写。")
        return EXIT_OK, secret

    text = config_path.read_text(encoding="utf-8")
    line = f"password = {_toml_str(secret)}"
    if re.search(r"^password\s*=.*$", text, re.MULTILINE):
        # 用函数做替换：re.sub 会把替换串里的 `\` 再吃一遍，`\"` 会退化成 `"`
        text = re.sub(r"^password\s*=.*$", lambda _m: line, text, count=1, flags=re.M)
    else:
        text += f"\n{line}\n"
    config_path.write_text(text, encoding="utf-8")
    _restrict(config_path)
    _say(f"钥匙串用不了，密码已写进配置文件（{_masked(secret)}，明文，注意别提交）。")
    return EXIT_OK, secret


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
    try:
        answer = input("要装成开机自启吗？断线会自动重连，随时可以卸。[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _say("")
        answer = ""
    if answer not in {"y", "yes"}:
        _say("没装自启。想装随时跑 `campus-auth install`。")
        return
    try:
        service = service_for(config_path)
        check_python(sys.executable)
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

    code = _ask_account(target, adapter_name, keep_account=keep)
    if code != EXIT_OK:
        return code

    config = load(target)
    code, secret = _save_password(target, config.account, adapter_name)
    if code != EXIT_OK:
        return code

    code = _verify(target, secret)
    _ask_autostart(target)
    _say("")
    _say(f"配置在 {target}；常用命令：`campus-auth status` / `login` / `watch` / `doctor`。")
    _say("出问题先跑 `campus-auth doctor`，把输出发出来（密码不会出现）。")
    return code


__all__ = ["cmd_setup"]
