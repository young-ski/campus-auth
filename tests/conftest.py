"""全局夹具：测试永远别碰真实的 state.json。"""

from __future__ import annotations

import pytest

from campus_auth import state


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(state.ENV_STATE, str(tmp_path / "state.json"))
