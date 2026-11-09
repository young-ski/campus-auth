#!/usr/bin/env python3
"""打一个发给同学的 Windows 压缩包：pyz + 校验和 + 安装说明 + 免责 + install.cmd。

    python tools/make_bundle.py                 # dist/campus-auth-<版本>-win.zip
    python tools/make_bundle.py out/x.zip

包里的 `install.cmd` 必须是纯 ASCII（cmd.exe 按 OEM 代码页读批处理，UTF-8 的
`echo` 在 cp936 上会乱码）且用 CRLF。中文全在 .txt 和 Python 里。
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(ROOT / "tools"))

import build_zipapp  # noqa: E402

# 包里放什么、叫什么；顺序就是同学解压后看到的顺序
PAYLOAD = {
    "install.cmd": "install.cmd",
    "install-guide.txt": "install-guide.txt",
    "disclaimer.txt": "disclaimer.txt",
}


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _check_bat() -> None:
    raw = (PACKAGING / "install.cmd").read_bytes()
    non_ascii = [i for i, byte in enumerate(raw) if byte > 0x7F]
    if non_ascii:
        raise SystemExit(f"install.cmd 有非 ASCII 字节（偏移 {non_ascii[:5]}），cmd.exe 会读成乱码")
    if b"\r\n" not in raw or raw.count(b"\n") != raw.count(b"\r\n"):
        raise SystemExit("install.cmd 必须是 CRLF 换行")


def main(argv: list[str]) -> int:
    _force_utf8()
    _check_bat()

    version = (ROOT / "src" / "campus_auth" / "__init__.py").read_text(encoding="utf-8")
    version = version.split('__version__ = "')[1].split('"')[0]
    default_name = f"campus-auth-{version}-win.zip"
    if argv:
        given = Path(argv[0])
        # 给目录（或以分隔符结尾）就在里面按版本号命名，省得调用方自己拼
        target = given / default_name if given.is_dir() or argv[0].endswith(("/", "\\")) else given
    else:
        target = ROOT / "dist" / default_name
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / f"campus-auth-{version}"
        stage.mkdir()
        code = build_zipapp.main([str(stage / "campus-auth.pyz")])
        if code != 0:
            return code
        for src, name in PAYLOAD.items():
            source = PACKAGING / src
            if source.suffix == ".txt":
                # 带 BOM：旧记事本和别的编辑器靠它认 UTF-8，不带就是一堆乱码
                (stage / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8-sig")
                continue
            shutil.copy2(source, stage / name)

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.iterdir()):
                archive.write(path, f"campus-auth-{version}/{path.name}")

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print()
    print(f"{target}  {target.stat().st_size} 字节")
    print(f"zip sha256 {digest}   （贴群里时一起给，同学能核对）")
    print("发之前自己解压跑一遍 install.cmd，别只信构建成功")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
