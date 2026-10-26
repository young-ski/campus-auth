from __future__ import annotations

import pytest

from campus_auth import keepalive
from campus_auth.errors import TransportError


class StubPortal:
    def __init__(self, *, online: bool = True, login_ok: bool = True) -> None:
        self.online = online
        self.login_ok = login_ok
        self.logins = 0

    def mine(self):
        return {"online": True} if self.online else None

    def login(self):
        self.logins += 1
        self.online = self.login_ok

        class Result:
            ok = self.login_ok
            msg = "认证成功" if self.login_ok else "被拒"

        return Result()


def test_watch_records_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: False)
    cycles: list[keepalive.Cycle] = []
    assert (
        keepalive.watch(
            lambda: StubPortal(),
            account="",
            password="",
            operator="",
            once=True,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 0
    )
    assert cycles and cycles[0].elapsed >= 0.0


def test_watch_marks_login_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: False)
    portal = StubPortal(online=False)
    cycles: list[keepalive.Cycle] = []
    assert (
        keepalive.watch(
            lambda: portal,
            account="",
            password="",
            operator="",
            once=True,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 0
    )
    assert portal.logins == 1
    assert cycles[0].attempted is True
    assert "已重新登录" in cycles[0].message


def test_watch_reports_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(StubPortal):
        def mine(self):
            raise TransportError("超时")

    cycles: list[keepalive.Cycle] = []
    assert (
        keepalive.watch(
            lambda: Broken(),
            account="",
            password="",
            operator="",
            once=True,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 1
    )
    assert cycles[0].ok is False
    assert "查在线状态失败" in cycles[0].message
