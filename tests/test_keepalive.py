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
            hint = ""

        return Result()


def test_watch_records_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: True)
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
    """DNS 通不算「无需登录」：门户说不在线就得登。"""
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: True)
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


def test_rejection_with_dns_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: True)
    cycles: list[keepalive.Cycle] = []
    portal = StubPortal(online=False, login_ok=False)
    assert (
        keepalive.watch(
            lambda: portal,
            account="",
            password="",
            operator="",
            once=True,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 1
    )
    assert cycles[0].ok is False
    assert "DNS 正常" in cycles[0].message


def test_three_rejections_with_dns_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """门户会话接口坏掉时，别把「用户已在线」当故障一路退避。"""
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: True)
    cycles: list[keepalive.Cycle] = []
    portal = StubPortal(online=False, login_ok=False)
    assert (
        keepalive.watch(
            lambda: portal,
            account="",
            password="",
            operator="",
            max_cycles=3,
            sleep=lambda _s: None,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 0
    )
    assert [cycle.ok for cycle in cycles] == [False, False, True]
    assert cycles[0].degraded is False
    assert cycles[2].degraded is True
    assert "连续" in cycles[2].message


def test_dns_down_keeps_counting_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: False)
    cycles: list[keepalive.Cycle] = []
    portal = StubPortal(online=False, login_ok=False)
    assert (
        keepalive.watch(
            lambda: portal,
            account="",
            password="",
            operator="",
            max_cycles=3,
            sleep=lambda _s: None,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 1
    )
    assert [cycle.ok for cycle in cycles] == [False, False, False]
    assert all(cycle.degraded is False for cycle in cycles)


def test_success_clears_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keepalive.net, "resolves", lambda _host: True)

    class ThirdTime(StubPortal):
        def login(self):
            self.logins += 1
            ok = self.logins >= 3
            self.online = ok

            class Result:
                pass

            result = Result()
            result.ok = ok
            result.msg = "认证成功" if ok else "被拒"
            result.hint = ""
            return result

    cycles: list[keepalive.Cycle] = []
    portal = ThirdTime(online=False, login_ok=False)
    assert (
        keepalive.watch(
            lambda: portal,
            account="",
            password="",
            operator="",
            max_cycles=3,
            sleep=lambda _s: None,
            on_cycle=lambda c, _i: cycles.append(c),
        )
        == 0
    )
    assert cycles[2].ok is True
    assert cycles[2].degraded is False
    assert "已重新登录" in cycles[2].message
