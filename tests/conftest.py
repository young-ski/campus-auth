"""全局夹具：测试永远别碰真实的系统钥匙串。"""

from __future__ import annotations

import pytest

from campus_auth import credentials


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch) -> None:
    """默认当钥匙串不可用；要用的测试自己把 `_backend` 换成假实现。"""
    monkeypatch.setattr(credentials, "_backend", lambda: None)
