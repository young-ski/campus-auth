#!/usr/bin/env python3
"""发布前的版本一致性检查：`pyproject.toml`、`__init__.__version__`、tag 三处必须一样。

只比 tag 是不够的 —— `--version` 读的是 `__init__`，两处能悄悄分家；而
`workflow_dispatch` 发布时干脆没有 tag。用法：

    python tools/check_version.py           # 只比源码两处
    python tools/check_version.py v1.4.0    # 再比 tag
"""

from __future__ import annotations

import contextlib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "campus_auth" / "__init__.py"


def _force_utf8() -> None:
    """别指望调用方的 locale：Windows runner 是 cp1252，中文 print 会炸。"""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    _force_utf8()
    with (ROOT / "pyproject.toml").open("rb") as handle:
        declared = str(tomllib.load(handle)["project"]["version"])
    match = re.search(r'__version__ = "([^"]+)"', INIT.read_text(encoding="utf-8"))
    if match is None:
        print(f"读不到 {INIT} 里的 __version__", file=sys.stderr)
        return 1
    packaged = match.group(1)

    problems = []
    if declared != packaged:
        problems.append(f"pyproject.toml 是 {declared}，__init__ 是 {packaged}")
    if argv and argv[0]:
        tag = argv[0].removeprefix("v")
        if tag != declared:
            problems.append(f"tag {argv[0]} 与版本 {declared} 不一致")

    for problem in problems:
        print(f"版本不一致: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"版本一致: {declared}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
