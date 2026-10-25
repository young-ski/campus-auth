from __future__ import annotations

import json
from pathlib import Path

import pytest

from campus_auth import state


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "state.json"
    monkeypatch.setenv(state.ENV_STATE, str(path))
    return path


def test_roundtrip(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == "idx1"
    saved = json.loads(store.read_text(encoding="utf-8"))["records"][0]
    assert saved["adapter"] == "ruijie"
    assert saved["userIndex"] == "idx1"


def test_scope_is_adapter_account_ip(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")
    assert state.load_user_index("ruijie", "2", "10.0.0.1") == ""
    assert state.load_user_index("ruijie", "1", "10.0.0.2") == ""
    assert state.load_user_index("srun", "1", "10.0.0.1") == ""


def test_save_overwrites_same_slot(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx2")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == "idx2"
    assert len(json.loads(store.read_text(encoding="utf-8"))["records"]) == 1


def test_expired_record_is_ignored(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")
    raw = json.loads(store.read_text(encoding="utf-8"))
    raw["records"][0]["ts"] -= state.TTL + 1
    store.write_text(json.dumps(raw), encoding="utf-8")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == ""


def test_expired_slot_is_pruned_on_save(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "old")
    raw = json.loads(store.read_text(encoding="utf-8"))
    raw["records"][0]["ts"] -= state.TTL + 1
    store.write_text(json.dumps(raw), encoding="utf-8")
    state.save_user_index("ruijie", "2", "10.0.0.1", "new")
    assert [r["userIndex"] for r in json.loads(store.read_text(encoding="utf-8"))["records"]] == [
        "new"
    ]


def test_drop(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")
    state.drop_user_index("ruijie", "1", "10.0.0.1")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == ""


def test_empty_index_is_not_saved(store: Path) -> None:
    state.save_user_index("ruijie", "1", "10.0.0.1", "")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == ""


def test_broken_file_counts_as_empty(store: Path) -> None:
    store.write_text("{ 这不是 json", encoding="utf-8")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == ""
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == "idx1"


def test_unwritable_path_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")  # 同名文件占位，mkdir 会失败
    monkeypatch.setenv(state.ENV_STATE, str(blocker / "state.json"))
    state.save_user_index("ruijie", "1", "10.0.0.1", "idx1")  # 不该抛
    assert state.load_user_index("ruijie", "1", "10.0.0.1") == ""
