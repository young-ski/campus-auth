#!/usr/bin/env python3
"""`install` 产物在三平台的转义自检（CI 用，也可本地跑）。

路径里塞 `&`、`%`、空格这些会让 cmd.exe / systemd / XML 出事的东西，逐项断言：

* Windows 的 `.cmd`：每个参数都有引号，`%` 写成 `%%`
* systemd 的 ExecStart：`%` 写成 `%%`，带空格的参数用引号
* launchd 的 plist：能当 XML 解析，`&` 已转义

不跑任何系统命令，三平台都能在任意机器上检查。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from campus_auth import install

HOSTILE_CONFIG = Path("C:/a&b/100% real/c.toml")
HOSTILE_PYTHON = "C:/py thon/python.exe"
FAILS: list[str] = []


def check(ok: bool, message: str) -> None:
    if ok:
        print(f"  ✓ {message}")
    else:
        print(f"  ✗ {message}")
        FAILS.append(message)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        with __import__("contextlib").suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print("Windows .cmd")
    win = install.service_for(HOSTILE_CONFIG, python=HOSTILE_PYTHON, platform="win32")
    exec_line = next(line for line in win.content.splitlines() if "campus_auth" in line)
    check(exec_line.count('"') >= 2 * 7, "每个参数都被引号包住")
    check("100%% real" in exec_line, "`%` 写成 `%%`，不会被 cmd 展开")
    check(f'"{str(HOSTILE_CONFIG).replace("%", "%%")}"' in exec_line, "含 `&` 的路径整体在引号里")

    print("systemd unit")
    unit = install.service_for(HOSTILE_CONFIG, python=HOSTILE_PYTHON, platform="linux")
    exec_unit = next(x for x in unit.content.splitlines() if x.startswith("ExecStart"))
    check("100%% real" in exec_unit, "`%` 写成 `%%`，不会被当 specifier")
    check('"C:/py thon/python.exe"' in exec_unit, "带空格的解释器路径加引号")

    print("launchd plist")
    plist = install.service_for(HOSTILE_CONFIG, python=HOSTILE_PYTHON, platform="darwin")
    try:
        ET.fromstring(plist.content)
        check(True, "plist 是合法 XML")
    except ET.ParseError as exc:
        check(False, f"plist 不是合法 XML: {exc}")
    check("a&amp;b" in plist.content, "`&` 已转义")

    print()
    if FAILS:
        print(f"{len(FAILS)} 项不通过")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
