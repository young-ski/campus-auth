from __future__ import annotations

import urllib.error

import pytest

from campus_auth.adapters.base import Adapter, Param
from campus_auth.adapters.huuc import ADAPTER as HUUC
from campus_auth.crypto import xor_unhex
from campus_auth.errors import TransportError
from campus_auth.portal import Portal, extract_json, iter_retry_delays

IP = "10.152.59.163"


def make_portal(adapter: Adapter = HUUC, ip: str = IP) -> Portal:
    return Portal(adapter, verify_tls=False, timeout=1, retries=0, ip=ip, mac="0" * 12)


# ---------- JSONP ----------


@pytest.mark.parametrize(
    "body",
    [
        '{"result":1}',
        'dr1003({"result":1})',
        'jsonp_123({"result":1, "msg":"ok"})',
        '  \n  {"a":{"b":2}}  ',
        'cb({"msg":"brace } inside"})',
        'cb({"msg":"quote \\" inside"})',
    ],
)
def test_extract_json_shapes(body: str) -> None:
    assert extract_json(body)


def test_extract_json_nested_string_braces() -> None:
    assert extract_json('cb({"msg":"a{b}c"})') == {"msg": "a{b}c"}


def test_extract_json_prefers_valid_object() -> None:
    assert extract_json('garbage {not json} then {"ok":1}') == {"ok": 1}


@pytest.mark.parametrize("body", ["", "no object here", "<html></html>"])
def test_extract_json_failure(body: str) -> None:
    with pytest.raises(TransportError):
        extract_json(body)


# ---------- URL ----------


def test_build_url_encodes_only_flagged() -> None:
    url = make_portal().build_url("/p", [Param("a", "1"), Param("plain", "1", encode=False)])
    assert "a=10" in url  # "1" ^ 0x21 == 0x10
    assert "plain=1" in url
    assert url.startswith("https://netauth.huuc.edu.cn:802/p?")


def test_build_url_keeps_operator_marker() -> None:
    url = make_portal().build_url(
        "/p", [Param("user_account", HUUC.format_account("0814", "cmcc"))]
    )
    assert xor_unhex(url.split("user_account=")[1], 0x21) == ",0,0814@cmcc"


def test_base_url_override() -> None:
    assert make_portal().base_url.startswith("https://")
    portal = Portal(HUUC, base_url="http://10.0.0.1:8080/", ip=IP)
    assert portal.base_url == "http://10.0.0.1:8080"


# ---------- 业务 ----------


def test_login_passes_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_get(self: Portal, path: str, params: list[Param]) -> dict:
        seen["path"] = path
        seen["account"] = dict((p.key, p.value) for p in params)["user_account"]
        return {"result": 1, "ret_code": 0}

    monkeypatch.setattr(Portal, "get", fake_get)
    result = make_portal().login("0814", "pw", "cmcc")
    assert result.ok
    assert seen["path"] == "/eportal/portal/login"
    assert seen["account"] == ",0,0814@cmcc"


def test_online_parses_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Portal,
        "get",
        lambda self, path, params: {
            "list": [{"online_ip": IP, "user_account": "0814", "time_long": "9"}, "junk"]
        },
    )
    sessions = make_portal().online()
    assert len(sessions) == 1
    assert sessions[0].ip == IP
    assert sessions[0].time_long == "9"


def test_mine_matches_own_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Portal, "get", lambda self, path, params: {"list": [{"online_ip": IP}]})
    assert make_portal().mine() is not None


def test_mine_ignores_other_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Portal, "get", lambda self, path, params: {"list": [{"online_ip": "10.9.9.9"}]}
    )
    assert make_portal().mine() is None


def test_logout_uses_logout_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}
    monkeypatch.setattr(Portal, "get", lambda self, path, params: seen.setdefault("p", path) and {})
    make_portal().logout()
    assert seen["p"] == "/eportal/portal/logout"


# ---------- 传输重试 ----------


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode()

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_get_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("boom")
        return FakeResponse('cb({"result":1})')

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda _: None)
    portal = Portal(HUUC, timeout=1, retries=2, ip=IP)
    assert portal.get("/p", []) == {"result": 1}
    assert calls["n"] == 3


def test_get_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, **kw: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    with pytest.raises(TransportError, match="请求失败"):
        Portal(HUUC, timeout=1, retries=1, ip=IP).get("/p", [])


def test_retry_delays_capped() -> None:
    delays = list(iter_retry_delays(10, base=1, cap=8))
    assert delays == sorted(delays)
    assert max(delays) <= 8
