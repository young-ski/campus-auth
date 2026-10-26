"""命令行入口：只有 parser、分之调度和退出码。

各子命令的实现都在 `commands.py`。
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
    EXIT_CONFIG,
    EXIT_ENV,
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
    password_p.add_argument("--show", action="store_true", help="只看有没有存，不写入")
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
