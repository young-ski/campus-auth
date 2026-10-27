from __future__ import annotations

import types

import pytest

from campus_auth import credentials


@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """把钥匙串换成内存实现，别碰真凭据库。"""
    store: dict[tuple[str, str], str] = {}

    def delete(service: str, user: str) -> None:
        store.pop((service, user))  # 没有就 KeyError，跟真 keyring 一致

    module = types.SimpleNamespace(
        get_keyring=lambda: object(),
        get_password=lambda service, user: store.get((service, user)),
        set_password=lambda service, user, secret: store.__setitem__((service, user), secret),
        delete_password=delete,
    )
    monkeypatch.setattr(credentials, "_backend", lambda: module)
    return store


def test_roundtrip(vault: dict) -> None:
    assert credentials.available() is True
    assert credentials.set("ruijie", "20240001", "pw") is True
    assert credentials.get("ruijie", "20240001") == "pw"
    assert vault[("campus-auth", "ruijie/20240001")] == "pw"  # 键里带适配层
    assert credentials.delete("ruijie", "20240001") is True
    assert credentials.get("ruijie", "20240001") == ""


def test_scoped_by_adapter_and_account(vault: dict) -> None:
    credentials.set("ruijie", "1", "a")
    credentials.set("srun", "1", "b")
    assert credentials.get("ruijie", "1") == "a"
    assert credentials.get("srun", "1") == "b"


def test_delete_missing_is_ok(vault: dict) -> None:
    credentials.set("ruijie", "1", "a")
    credentials.delete("ruijie", "1")
    assert credentials.delete("ruijie", "1") is True  # 幂等


def test_empty_inputs_are_ignored(vault: dict) -> None:
    assert credentials.set("", "1", "a") is False
    assert credentials.set("ruijie", "1", "") is False
    assert credentials.get("", "") == ""


def test_backend_errors_are_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args):
        raise RuntimeError("vault 锁了")

    module = types.SimpleNamespace(
        get_keyring=boom, get_password=boom, set_password=boom, delete_password=boom
    )
    monkeypatch.setattr(credentials, "_backend", lambda: module)
    assert credentials.available() is False
    assert credentials.get("ruijie", "1") == ""
    assert credentials.set("ruijie", "1", "a") is False
    assert credentials.delete("ruijie", "1") is False  # 后端报错不能报成功


def test_without_keyring_package() -> None:
    """conftest 默认就把后端关掉，等价于没装 keyring。"""
    assert credentials.available() is False
    assert credentials.get("ruijie", "1") == ""
    assert credentials.set("ruijie", "1", "a") is False
    assert credentials.delete("ruijie", "1") is False


def test_delete_reports_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """后端锁着时不能报成功，否则 `--forget` 会骗人。"""

    def boom(*_args):
        raise RuntimeError("vault 锁了")

    module = types.SimpleNamespace(
        get_keyring=lambda: object(), delete_password=boom, get_password=lambda *a: None
    )
    monkeypatch.setattr(credentials, "_backend", lambda: module)
    assert credentials.delete("huuc", "1") is False


def test_delete_missing_entry_is_still_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """「本来就没有」是幂等成功，别跟后端报错混为一谈。"""

    class PasswordDeleteError(Exception):
        pass

    def missing(*_args):
        raise PasswordDeleteError("not found")

    module = types.SimpleNamespace(get_keyring=lambda: object(), delete_password=missing)
    monkeypatch.setattr(credentials, "_backend", lambda: module)
    assert credentials.delete("huuc", "1") is True


def test_available_rejects_the_fail_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """`keyring.backends.fail.Keyring` 永远抛异常，但 `is not None` 会判真。"""

    class Keyring:
        pass

    Keyring.__module__ = "keyring.backends.fail"
    monkeypatch.setattr(credentials, "_backend", lambda: types.SimpleNamespace(get_keyring=Keyring))
    assert credentials.available() is False
