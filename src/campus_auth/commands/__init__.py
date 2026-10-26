"""各子命令的出口。

`cli.py` 只从这里取命令函数；实现按域分在下面几个模块里，共用工具在 `_common`。
"""

from __future__ import annotations

import getpass  # noqa: F401  测试会 patch commands.getpass

from ._common import _config, _dump, _err, _prepare, _say  # noqa: F401
from .account import cmd_password
from .admin import cmd_adapters, cmd_init, cmd_install, cmd_uninstall, cmd_urls
from .auth import cmd_check, cmd_login, cmd_logout, cmd_status, cmd_unbind
from .scan import cmd_probe
from .watch import cmd_watch

__all__ = [
    "cmd_adapters",
    "cmd_check",
    "cmd_init",
    "cmd_install",
    "cmd_login",
    "cmd_logout",
    "cmd_password",
    "cmd_probe",
    "cmd_status",
    "cmd_unbind",
    "cmd_uninstall",
    "cmd_urls",
    "cmd_watch",
]
