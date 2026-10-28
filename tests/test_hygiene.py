"""文档与注释不许跟代码对着干，死代码不许留着充数。"""

from __future__ import annotations

from pathlib import Path

import json_schema_check
import pytest

from campus_auth import cli, probe

ROOT = Path(__file__).resolve().parents[1]


def test_cli_docstring_points_at_the_package() -> None:
    text = cli.__doc__ or ""
    assert "commands/" in text
    assert "commands.py" not in text


def test_probe_docstring_matches_max_js() -> None:
    text = probe.collect.__doc__ or ""
    assert "1 个" in text
    assert "跨源" in text


def test_schema_checker_docstring_lists_anyof() -> None:
    text = json_schema_check.__doc__ or ""
    assert "anyOf" in text  # 实现的是 anyOf，别写成 oneOf
    assert "不支持" in text


def test_retry_helper_is_actually_wired_up() -> None:
    """`iter_retry_delays` 以前只被测试调用、运行时走的是内联退避。"""
    text = (ROOT / "src" / "campus_auth" / "portal.py").read_text(encoding="utf-8")
    assert text.count("iter_retry_delays(") >= 2  # 一处定义 + 至少一处调用


@pytest.mark.parametrize("version", ["1.3.0", "1.2.1", "1.2.0"])
def test_changelog_sections_are_not_duplicated(version: str) -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.count(f"## {version}\n") == 1


def test_readme_documents_the_adapter_escape_hatch() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "module:attr" in text or ".py:ADAPTER" in text


def test_school_catalog_exists() -> None:
    text = (ROOT / "docs" / "schools.md").read_text(encoding="utf-8")
    assert "huuc" in text
    assert "待验证" in text


def test_adapters_command_points_at_the_catalog() -> None:
    source = (ROOT / "src" / "campus_auth" / "commands" / "admin.py").read_text(encoding="utf-8")
    assert "schools.md" in source


def test_portal_has_no_unreachable_tail_raise() -> None:
    text = (ROOT / "src" / "campus_auth" / "portal.py").read_text(encoding="utf-8")
    assert "请求失败（已重试 {self.retries} 次）: {self.last_url}" not in text


def test_security_policy_exists_and_names_a_private_channel() -> None:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Security" in text or "advisories" in text
    assert "密码" in text


def test_pr_template_asks_for_the_checks() -> None:
    text = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "pytest" in text
    assert "ruff" in text


def test_bug_template_asks_for_the_install_method() -> None:
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml").read_text(encoding="utf-8")
    assert "安装方式" in text
    assert "probe --json" in text


def test_readme_lists_doctor_and_points_at_security() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "doctor" in text
    assert "SECURITY.md" in text


def test_readme_has_an_english_first_screen() -> None:
    """README 全中文，非中文读者第一屏就掉队。"""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    head = text[:4000]
    assert "**English**" in head


def test_school_catalog_states_its_entry_criteria() -> None:
    text = (ROOT / "docs" / "schools.md").read_text(encoding="utf-8")
    assert "收录标准" in text
    assert "probe" in text


def test_readme_says_how_to_install_a_third_party_adapter() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "entry point" in text.lower() or "entry_points" in text
