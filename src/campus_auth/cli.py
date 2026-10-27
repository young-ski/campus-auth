"""命令行入口：只有 parser、分之调度和退出码。

各子命令的实现都在 `commands/` 包里。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import traceback

from . import __version__, adapters
from .commands import (
    _dump,
    _err,
    cmd_adapters,
    cmd_check,
    cmd_init,
    cmd_install,
    cmd_login,
    cmd_logout,
    cmd_password,
    cmd_probe,
    cmd_status,
    cmd_unbind,
    cmd_uninstall,
    cmd_urls,
    cmd_watch,
)
from .errors import (
    EXIT_OK,
    CampusAuthError,
    ConfigError,
    EnvironmentError_,
)

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="campus-auth",
        description="Dr.COM / eportal 校园网门户认证客户端",
        epilog="适配层用 --adapter 选，内置: " + ", ".join(adapters.names()),
    )
    parser.add_argument("--version", action="version", version=f"campus-auth {__version__}")
    parser.add_argument(
        "--show-secrets", action="store_true", help="报错里的密码不打码（默认打码）"
    )
    # 参数分三档：每个命令只挂它真用得上的，别让 `probe --help` 里冒 --password-stdin
    essential = argparse.ArgumentParser(add_help=False)
    essential.add_argument("--config", metavar="路径", help="配置文件路径")
    essential.add_argument("-a", "--account", metavar="学号", help="学号，纯数字，不带 @ 后缀")
    essential.add_argument(
        "-p", "--password", metavar="密码", help="密码（会留在 shell 历史里，推荐 password 子命令）"
    )
    essential.add_argument("--password-stdin", action="store_true", help="从标准输入读密码")
    essential.add_argument("--json", action="store_true", help="输出 JSON，给脚本读")

    identity = argparse.ArgumentParser(add_help=False)
    identity.add_argument("--adapter", metavar="名", help="换适配层，或 module:attr")
    identity.add_argument("--url", metavar="地址", help="覆盖门户地址")
    identity.add_argument("--ip", metavar="IP", help="覆盖本机 IP（排障 / 离线生成 URL）")
    identity.add_argument("--mac", metavar="MAC", help="覆盖 MAC（12 位十六进制）")

    tuning = argparse.ArgumentParser(add_help=False)
    tuning.add_argument("--timeout", type=float, metavar="秒", help="单次请求超时")
    tuning.add_argument("--retries", type=int, metavar="次", help="传输重试次数")
    tuning.add_argument(
        "--verify-tls",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="校验证书（默认不校验；--no-verify-tls 覆盖配置里的 true）",
    )

    # 只带账号、不带密码的父参数（注销 / 解绑 / 状态 / 检查都不需要密码）
    accounting = argparse.ArgumentParser(add_help=False)
    accounting.add_argument("--config", metavar="路径", help="配置文件路径")
    accounting.add_argument("-a", "--account", metavar="学号", help="学号，纯数字，不带 @ 后缀")
    accounting.add_argument("--json", action="store_true", help="输出 JSON，给脚本读")

    # 什么身份参数都没有的命令
    minimal = argparse.ArgumentParser(add_help=False)
    minimal.add_argument("--config", metavar="路径", help="配置文件路径")
    minimal.add_argument("--json", action="store_true", help="输出 JSON，给脚本读")

    # 不实现 --json 的命令就用这两个：宁可 argparse 报错，也别静默吃 flag
    plain = argparse.ArgumentParser(add_help=False)
    plain.add_argument("--config", metavar="路径", help="配置文件路径")

    creds = argparse.ArgumentParser(add_help=False)
    creds.add_argument("--config", metavar="路径", help="配置文件路径")
    creds.add_argument("-a", "--account", metavar="学号", help="学号，纯数字，不带 @ 后缀")
    creds.add_argument("-p", "--password", metavar="密码", help="密码（会留在 shell 历史里）")
    creds.add_argument("--password-stdin", action="store_true", help="从标准输入读密码")

    auth_parents = [essential, identity, tuning]
    sub = parser.add_subparsers(dest="command", required=True, metavar="命令")

    init = sub.add_parser(
        "init",
        parents=[plain, identity],
        help="生成配置模板",
        description="写一份配置模板。填 account、存密码之后再跑 status 自检。",
    )
    init.add_argument("-o", "--output", metavar="路径", help="写到哪个文件")
    init.add_argument("-f", "--force", action="store_true", help="覆盖已有文件")
    init.set_defaults(func=cmd_init)

    sub.add_parser(
        "adapters",
        parents=[plain],
        help="列出内置适配层与验证状态",
        description="看内置了哪些学校。加自己学校时照 generic 复制一份。",
    ).set_defaults(func=cmd_adapters)

    login_p = sub.add_parser(
        "login",
        parents=auth_parents,
        help="登录",
        description="认证一次。宿舍网段要 -w cmcc / -w unicom，教学楼不加。",
    )
    login_p.add_argument(
        "-w", "--operator", metavar="运营商", help="宿舍才需要：cmcc / unicom / dx"
    )
    login_p.add_argument("--remember", action="store_true", help="成功后把密码存进系统钥匙串")
    login_p.set_defaults(func=cmd_login)

    sub.add_parser(
        "logout",
        parents=[essential, identity, tuning],
        help="注销当前账号",
        description="让门户断开这台机器的会话。",
    ).set_defaults(func=cmd_logout)

    sub.add_parser(
        "unbind",
        parents=[essential, identity, tuning],
        help="解除 IP / MAC 绑定",
        description="换设备或提示 IP 被绑时用。只解绑，不注销。",
    ).set_defaults(func=cmd_unbind)

    sub.add_parser(
        "status",
        parents=[accounting, identity, tuning],
        help="看会话，标出哪条是你的",
        description="列出本 IP 与门户里的会话。没填 account 会直接指出来。",
    ).set_defaults(func=cmd_status)

    check = sub.add_parser(
        "check",
        parents=[accounting, identity, tuning],
        help="只判定在线，结果走退出码",
        description="给脚本和监控用：在线 0、不在线 1、环境问题 3、传输问题 4。",
    )
    check.add_argument("-q", "--quiet", action="store_true", help="不输出，只看退出码")
    check.set_defaults(func=cmd_check)

    probe_p = sub.add_parser(
        "probe",
        parents=[minimal, identity, tuning],
        help="先认门户是不是 Dr.COM",
        description="只请求匿名接口，不要账号密码。必须从校园网内跑。",
    )
    probe_p.add_argument("--no-follow", action="store_true", help="不跟随劫持页给的跳转地址")
    probe_p.set_defaults(func=cmd_probe)

    urls = sub.add_parser(
        "urls",
        parents=[creds, identity, tuning],
        help="为当前 IP 生成快捷方式",
        description="生成 .url / .desktop。里面的密码是可还原的密文，别随手分享。",
    )
    urls.add_argument("-o", "--output", metavar="目录", help="输出目录")
    urls.set_defaults(func=cmd_urls)

    watch_p = sub.add_parser(
        "watch",
        parents=auth_parents,
        help="断线自动重连",
        description="前台保活循环。长期跑用 install 装成登录自启。",
    )
    watch_p.add_argument(
        "-w", "--operator", metavar="运营商", help="宿舍才需要：cmcc / unicom / dx"
    )
    watch_p.add_argument("--once", action="store_true", help="只跑一轮")
    watch_p.add_argument("--cycles", type=int, metavar="轮数", help="跑多少轮后退出")
    watch_p.add_argument("--interval", type=float, metavar="秒", help="两轮间隔秒数")
    watch_p.add_argument(
        "--log", metavar="路径", help="同时写进这个文件（按 1 MiB 轮转，留一份 .1）"
    )
    watch_p.set_defaults(func=cmd_watch)

    password_p = sub.add_parser(
        "password",
        parents=[creds, identity],
        help="密码存进 / 删出系统钥匙串",
        description="交互式输入（不回显）；管道里则读一行。",
    )
    password_p.add_argument("--forget", action="store_true", help="删掉存着的密码")
    password_p.add_argument("--show", action="store_true", help="只看有没有存，不写入")
    password_p.set_defaults(func=cmd_password)

    install_p = sub.add_parser(
        "install",
        parents=[plain, identity],
        help="把 watch 装成登录自启",
        description="Windows 写 HKCU Run、Linux 写 systemd 用户单元、macOS 写 LaunchAgent。",
    )
    install_p.add_argument("--dry-run", action="store_true", help="只打印要写什么、跑什么")
    install_p.set_defaults(func=cmd_install)

    uninstall_p = sub.add_parser(
        "uninstall",
        parents=[plain, identity],
        help="卸掉 install 装的自启",
        description="停掉并删除 install 写下的东西。",
    )
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
    except (ConfigError, EnvironmentError_, CampusAuthError) as exc:
        # 人读的一律进 stderr；要 JSON 的话 stdout 上补一份机器可读的错误对象
        prefix = {
            ConfigError: "配置: ",
            EnvironmentError_: "环境: ",
        }.get(type(exc), "")
        _err(f"{prefix}{exc}")
        if getattr(args, "json", False):
            _dump({"ok": False, "error": str(exc)})
        return exc.exit_code
    except KeyboardInterrupt:
        _err("已中断")
        return 130
    except (BrokenPipeError, OSError) as exc:
        # `campus-auth ... | head` 会在这里断掉；Windows 上是 errno 22，POSIX 是 32
        if isinstance(exc, BrokenPipeError) or getattr(exc, "errno", None) in {22, 32}:
            with contextlib.suppress(OSError, ValueError):
                sys.stdout = open(os.devnull, "w")  # noqa: SIM115
            return EXIT_OK
        _err(f"意外错误: {exc!r}")
        traceback.print_exc()
        return 70
    except Exception as exc:  # 未预期的错误给 traceback，别静默
        _err(f"意外错误: {exc!r}")
        traceback.print_exc()
        return 70


if __name__ == "__main__":
    sys.exit(main())
