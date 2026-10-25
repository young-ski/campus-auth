from __future__ import annotations

import datetime
import email.message
import email.utils
import io
import urllib.error

import pytest

from campus_auth.adapters.base import Adapter, Param, Request
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
    req = Request("/p", params=[Param("a", "1"), Param("plain", "1", encode=False)])
    url = make_portal().build_url(req)
    assert "a=10" in url  # "1" ^ 0x21 == 0x10
    assert "plain=1" in url
    assert url.startswith("https://netauth.huuc.edu.cn:802/p?")


def test_build_url_keeps_operator_marker() -> None:
    req = Request("/p", params=[Param("user_account", HUUC.format_account("0814", "cmcc"))])
    url = make_portal().build_url(req)
    assert xor_unhex(url.split("user_account=")[1], 0x21) == ",0,0814@cmcc"


def test_build_url_accepts_absolute_url() -> None:
    url = make_portal().build_url(Request("http://1.2.3.4/eportal/InterFace.do?method=login"))
    assert url.startswith("http://1.2.3.4/eportal/InterFace.do")


def test_build_url_uses_ampersand_when_path_has_query() -> None:
    """InterFace.do?method=login 这类路径本身带 query，不能再塞第二个问号。"""
    url = make_portal().build_url(
        Request("http://h/eportal/InterFace.do?method=logout", params=[Param("a", "1")])
    )
    assert "?method=logout&a=1" in url
    assert "?method=logout?" not in url


def test_base_url_override() -> None:
    assert make_portal().base_url.startswith("https://")
    portal = Portal(HUUC, base_url="http://10.0.0.1:8080/", ip=IP)
    assert portal.base_url == "http://10.0.0.1:8080"


# ---------- 业务 ----------


def test_login_passes_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake(self: Portal, request: Request) -> dict:
        seen["path"] = request.path
        seen["account"] = dict((p.key, p.value) for p in request.params)["user_account"]
        return {"result": 1, "ret_code": 0}

    monkeypatch.setattr(Portal, "request", fake)
    portal = make_portal()
    portal.account, portal.password, portal.operator = "0814", "pw", "cmcc"
    assert portal.login().ok
    assert seen["path"] == "/eportal/portal/login"
    assert seen["account"] == ",0,0814@cmcc"


def test_body_uses_encoder() -> None:
    portal = make_portal()
    body = portal._body(Request("/x", method="POST", body={"plain": "1"}))
    assert b"plain=10" in body  # 值同样被 xor 成 10


def test_online_parses_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Portal,
        "request",
        lambda self, req: {
            "list": [{"online_ip": IP, "user_account": "0814", "time_long": "9"}, "junk"]
        },
    )
    sessions = make_portal().sessions()
    assert len(sessions) == 1
    assert sessions[0].ip == IP
    assert sessions[0].time_long == "9"


def test_mine_matches_own_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Portal, "request", lambda self, req: {"list": [{"online_ip": IP}]})
    assert make_portal().mine() is not None


def test_mine_ignores_other_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Portal, "request", lambda self, req: {"list": [{"online_ip": "10.9.9.9"}]})
    assert make_portal().mine() is None


def test_mine_uses_adapter_online_check() -> None:
    portal = make_portal()
    asserted = {}

    class AlwaysOff(type(HUUC)):
        def online_check(self, _portal):
            asserted["hit"] = True
            return False

    portal.adapter = AlwaysOff()
    assert portal.mine() is None
    assert asserted["hit"]


def test_logout_uses_logout_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake(self, req: Request) -> dict:
        seen["p"] = req.path
        return {}

    monkeypatch.setattr(Portal, "request", fake)
    make_portal().logout()
    assert seen["p"] == "/eportal/portal/logout"


# ---------- 传输重试 ----------


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode()

    def read(self, _limit: int | None = None) -> bytes:
        return self.body

    def close(self) -> None:  # HTTPError 会当它是文件对象去 close
        return None

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_request_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("boom")
        return FakeResponse('cb({"result":1})')

    monkeypatch.setattr("time.sleep", lambda _: None)
    portal = Portal(HUUC, timeout=1, retries=2, ip=IP)
    monkeypatch.setattr(portal._opener, "open", flaky)
    assert portal.request(Request("/p")) == {"result": 1}
    assert calls["n"] == 3


def test_request_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url, **kwargs):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("time.sleep", lambda _: None)
    portal = Portal(HUUC, timeout=1, retries=1, ip=IP)
    monkeypatch.setattr(portal._opener, "open", boom)
    with pytest.raises(TransportError, match="请求失败"):
        portal.request(Request("/p"))


def test_retry_delays_capped() -> None:
    delays = list(iter_retry_delays(10, base=1, cap=8))
    assert delays == sorted(delays)
    assert max(delays) <= 8


def http_error(code: int, retry_after: str | None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x/p", code, "boom", headers, io.BytesIO(b'{"ok":1}'))


def opener_from(monkeypatch: pytest.MonkeyPatch, portal: Portal, seq: list) -> None:
    """按顺序回放响应；异常对象就抛出来。"""

    def fake_open(*_a, **_k):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(portal._opener, "open", fake_open)


def test_retry_after_seconds_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    seq = [http_error(429, "1"), FakeResponse('{"result":1}')]

    monkeypatch.setattr("time.sleep", slept.append)
    portal = Portal(HUUC, timeout=1, retries=1, ip=IP)
    opener_from(monkeypatch, portal, seq)
    assert portal.request(Request("/p")) == {"result": 1}
    assert slept == [pytest.approx(1.0)]


def test_retry_after_http_date_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 也允许日期格式；以前 float() 直接吃不下，会抛 ValueError 变成退出码 70。"""
    when = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=3)
    stamp = email.utils.format_datetime(when)
    slept: list[float] = []
    seq = [http_error(503, stamp), FakeResponse('{"result":1}')]

    monkeypatch.setattr("time.sleep", slept.append)
    portal = Portal(HUUC, timeout=1, retries=1, ip=IP)
    opener_from(monkeypatch, portal, seq)
    assert portal.request(Request("/p")) == {"result": 1}
    assert len(slept) == 1
    assert 1.5 < slept[0] <= 4.0


def test_retry_after_garbage_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    seq = [http_error(429, "不久之后"), FakeResponse('{"result":1}')]

    monkeypatch.setattr("time.sleep", slept.append)
    portal = Portal(HUUC, timeout=1, retries=1, ip=IP)
    opener_from(monkeypatch, portal, seq)
    portal.request(Request("/p"))
    assert slept == [pytest.approx(2.0)]


def test_retry_after_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    seq = [http_error(429, "9999"), FakeResponse('{"result":1}')]

    monkeypatch.setattr("time.sleep", slept.append)
    portal = Portal(HUUC, timeout=1, retries=1, ip=IP)
    opener_from(monkeypatch, portal, seq)
    portal.request(Request("/p"))
    assert slept == [pytest.approx(60.0)]
