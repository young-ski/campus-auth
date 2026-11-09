"""发给同学的那个压缩包：命令行脚本的编码、包内清单、校验和都得对。

`install.cmd` 一旦混进 UTF-8 中文，cmd.exe 会按 OEM 代码页读成乱码 —— 而且是在
同学双击的那一刻才暴露。这里把它钉死。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BAT = PACKAGING / "install.cmd"


def test_bat_is_pure_ascii() -> None:
    raw = BAT.read_bytes()
    bad = [(i, byte) for i, byte in enumerate(raw) if byte > 0x7F]
    assert not bad, f"install.cmd 有非 ASCII 字节: {bad[:5]}"


def test_bat_uses_crlf() -> None:
    raw = BAT.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n")


def test_bat_propagates_the_setup_exit_code() -> None:
    text = BAT.read_text(encoding="ascii")
    assert "if errorlevel 1 goto :failed" in text


def test_bat_refuses_to_run_without_the_payload() -> None:
    text = BAT.read_text(encoding="ascii")
    assert ":no_pyz" in text
    assert "Unzip the whole folder first" in text


def test_bat_sends_people_to_the_guide_without_python() -> None:
    text = BAT.read_text(encoding="ascii")
    assert "install-guide.txt" in text
    assert "python.org/downloads" in text


def test_guide_covers_the_non_obvious_steps() -> None:
    text = (PACKAGING / "install-guide.txt").read_text(encoding="utf-8-sig")
    assert "热点" in text  # 认证前装不了东西
    assert "Add python.exe to PATH" in text
    assert "uninstall" in text
    assert "doctor" in text


def test_disclaimer_names_the_private_channel() -> None:
    text = (PACKAGING / "disclaimer.txt").read_text(encoding="utf-8-sig")
    assert "自担风险" in text
    assert "security/advisories/new" in text
    assert "不改" in text


def test_bundle_has_the_expected_files(tmp_path: Path) -> None:
    target = tmp_path / "b.zip"
    subprocess.run(
        [sys.executable, "tools/make_bundle.py", str(target)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    names = sorted(name.rsplit("/", 1)[-1] for name in zipfile.ZipFile(target).namelist())
    assert names == [
        "SHA256SUMS",
        "campus-auth.pyz",
        "disclaimer.txt",
        "install-guide.txt",
        "install.cmd",
    ]


def test_bundle_checksum_matches_the_pyz(tmp_path: Path) -> None:
    target = tmp_path / "b.zip"
    subprocess.run(
        [sys.executable, "tools/make_bundle.py", str(target)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    with zipfile.ZipFile(target) as archive:
        pyz = next(n for n in archive.namelist() if n.endswith("campus-auth.pyz"))
        sums = next(n for n in archive.namelist() if n.endswith("SHA256SUMS"))
        digest = hashlib.sha256(archive.read(pyz)).hexdigest()
        recorded = archive.read(sums).decode().split()[0]
    assert digest == recorded


@pytest.mark.parametrize("name", ["install.cmd", "install-guide.txt", "disclaimer.txt"])
def test_packaging_files_are_not_empty(name: str) -> None:
    assert (PACKAGING / name).stat().st_size > 200


def test_bundle_txt_files_carry_a_bom(tmp_path: Path) -> None:
    """不带 BOM 的 UTF-8 中文在旧记事本里是乱码；包里必须是 BOM 版。"""
    target = tmp_path / "b.zip"
    subprocess.run(
        [sys.executable, "tools/make_bundle.py", str(target)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    with zipfile.ZipFile(target) as archive:
        for name in archive.namelist():
            if name.endswith(".txt"):
                assert archive.read(name).startswith(b"\xef\xbb\xbf"), name
