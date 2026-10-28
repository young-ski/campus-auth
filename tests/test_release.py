"""发布链的自查：版本、tag、产物都由流水线自己保证，不靠记忆。

这些断言的价值在于「改坏了会红」，不是描述现状 —— 任何一条通过都意味着
一个曾经靠人手滑的步骤现在被机器盯着。
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from campus_auth import __version__

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
GITATTR = (ROOT / ".gitattributes").read_text(encoding="utf-8")


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def test_pyproject_and_package_version_agree() -> None:
    assert project_version() == __version__


def test_check_version_script_accepts_matching_tag() -> None:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/check_version.py", f"v{project_version()}"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_check_version_script_rejects_drifted_tag() -> None:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/check_version.py", "v9.9.9"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    assert "9.9.9" in result.stdout + result.stderr


def test_check_version_script_checks_sources_without_a_tag() -> None:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/check_version.py"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_version_guard_is_not_tag_only() -> None:
    """`workflow_dispatch` 曾能整段绕过校验，因为守卫被 if 包住了。"""
    guard = PUBLISH.split("check_version.py")[0]
    assert "if: startsWith(github.ref, 'refs/tags/v')" not in guard.split("- name:")[-1]


def test_publish_runs_tests_before_uploading() -> None:
    assert "pytest" in PUBLISH
    assert PUBLISH.index("pytest") < PUBLISH.index("pypi-publish")


def test_publish_builds_the_zipapp_and_checksums() -> None:
    assert "build_zipapp" in PUBLISH
    assert "SHA256SUMS" in PUBLISH


def test_publish_may_create_a_release() -> None:
    """没有 contents: write 就建不了 Release，pyz 只能继续手传。"""
    assert "contents: write" in PUBLISH
    assert "gh release create" in PUBLISH


def test_pyz_is_marked_binary() -> None:
    assert "*.pyz binary" in GITATTR


def test_zipapp_has_no_build_residue(tmp_path: Path) -> None:
    """以前 pyz 里夹着 31 个 .pyc 和整个 egg-info，纯属徒手 zip 的残留。"""
    target = tmp_path / "campus-auth.pyz"
    subprocess.run([sys.executable, "tools/build_zipapp.py", str(target)], cwd=ROOT, check=True)
    names = zipfile.ZipFile(target).namelist()
    assert "__main__.py" in names
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]
    assert not [name for name in names if ".egg-info" in name]


def test_zipapp_runs(tmp_path: Path) -> None:
    target = tmp_path / "campus-auth.pyz"
    subprocess.run([sys.executable, "tools/build_zipapp.py", str(target)], cwd=ROOT, check=True)
    result = subprocess.run(
        [sys.executable, str(target), "adapters"], capture_output=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr
    assert "huuc" in result.stdout


@pytest.mark.parametrize("word", ["sha256", "SHA256SUMS"])
def test_build_script_writes_a_checksum(word: str) -> None:
    assert word.lower() in (ROOT / "tools" / "build_zipapp.py").read_text(encoding="utf-8").lower()


def test_check_version_script_tolerates_empty_tag() -> None:
    """dispatch 运行没有 tag，要让守卫退化成只比两处源码。"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/check_version.py", ""],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", ["tools/build_zipapp.py", "tools/check_version.py"])
def test_tools_survive_a_non_utf8_locale(tmp_path: Path, script: str) -> None:
    """GitHub 的 Windows runner 是 cp1252；脚本直接 print 中文会 UnicodeEncodeError。"""
    env = {**__import__("os").environ, "PYTHONIOENCODING": "cp1252"}
    argv = [sys.executable, script]
    if script.endswith("build_zipapp.py"):
        argv.append(str(tmp_path / "x.pyz"))
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, encoding="utf-8", env=env)
    assert result.returncode == 0, result.stderr[-800:]
