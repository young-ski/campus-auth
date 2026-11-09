#!/usr/bin/env python3
"""打包单文件 `campus-auth.pyz`，并写出 `SHA256SUMS`。

只收 `src/` 里的真源码：`__pycache__`、`*.pyc`、`*.egg-info` 都是本机残留，
以前用 `python -m zipapp src` 直接压，402 KB 里有相当一部分是它们。

    python tools/build_zipapp.py dist/campus-auth.pyz
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info")

# zipapp 的 `main=` 生成的 __main__.py 只调 `main()`、**不 sys.exit**，
# 于是 pyz 永远退 0 —— 退出码契约在单文件形态上整个失效。自己写一个。
ENTRY = """\
import sys

from campus_auth.cli import main

sys.exit(main())
"""


def _force_utf8() -> None:
    """别指望调用方的 locale：Windows runner 是 cp1252，中文 print 会炸。"""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    _force_utf8()
    target = Path(argv[0]) if argv else ROOT / "dist" / "campus-auth.pyz"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "src"
        shutil.copytree(SRC, stage, ignore=IGNORE)
        (stage / "__main__.py").write_text(ENTRY, encoding="utf-8")
        zipapp.create_archive(stage, target, compressed=True)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    sums = target.with_name("SHA256SUMS")
    sums.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"{target}  {target.stat().st_size} 字节")
    print(f"sha256 {digest}")
    print(f"校验和写到 {sums}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
