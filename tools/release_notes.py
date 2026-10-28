#!/usr/bin/env python3
"""从 CHANGELOG 切出某个版本的说明，给 Release 用。

标题可能带日期（`## 1.7.0（2026-10-28）`），所以按前缀匹配、并要求版本号后面不是数字，
别让 1.7.0 抢了 1.7.01 的段落。找不到就退 1，让调用方退回别的内容。

    python tools/release_notes.py v1.7.0
"""

from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _force_utf8() -> None:
    """别指望调用方的 locale：Windows runner 是 cp1252。"""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def notes_for(version: str, text: str) -> str:
    version = version.removeprefix("v")
    heading = re.compile(rf"^##\s+{re.escape(version)}(?![\d.])")
    body: list[str] = []
    keep = False
    for line in text.splitlines():
        if line.startswith("## "):
            keep = bool(heading.match(line))
            continue
        if keep:
            body.append(line)
    return "\n".join(body).strip()


def main(argv: list[str]) -> int:
    _force_utf8()
    if not argv:
        print("用法: release_notes.py <版本|v版本>", file=sys.stderr)
        return 2
    version = argv[0]
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    body = notes_for(version, text)
    if not body:
        print(f"CHANGELOG 里没有 {version} 的段落", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
