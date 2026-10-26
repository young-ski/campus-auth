"""密码进钥匙串。"""

from __future__ import annotations

import argparse
import getpass
import sys

from .. import credentials
from ..config import Config
from ..errors import EXIT_CONFIG, EXIT_ENV, EXIT_OK, EXIT_REJECTED
from ._common import _config, _say


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
