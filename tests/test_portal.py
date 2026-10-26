from __future__ import annotations

import datetime
import email.utils
import urllib.error
import urllib.parse

import pytest
from fake_transport import FakeTransport

from campus_auth.adapters.base import Adapter, Param, Request
from campus_auth.adapters.huuc import ADAPTER as HUUC
from campus_auth.adapters.huuc import key_for
from campus_auth.crypto import xor_unhex
from campus_auth.errors import ParseError, TransportError
from campus_auth.portal import Portal, _mask_url, extract_json, iter_retry_delays

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
    with pytest.raises(ParseError):
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


def test_login_passes_operator() -> None:
    transport = FakeTransport((200, '{"result":1,"ret_code":0}'))
    portal = Portal(HUUC, timeout=1, retries=0, ip=IP, transport=transport)
    portal.account, portal.password, portal.operator = "0814", "pw", "cmcc"
    assert portal.login().ok
    assert "/eportal/portal/login" in transport.last_url
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(transport.last_url).query)
    encrypted = query["user_account"][0]
    assert xor_unhex(encrypted, key_for(IP)) == ",0,0814@cmcc"


def test_body_uses_encoder() -> None:
    portal = make_portal()
    body = portal._body(Request("/x", method="POST", body={"plain": "1"}))
    assert b"plain=10" in body  # 值同样被 xor 成 10


def test_online_parses_rows() -> None:
    body = f'cb({{"list":[{{"online_ip":"{IP}","user_account":"0814","time_long":"9"}},"junk"]}})'
    portal = Portal(HUUC, timeout=1, retries=0, ip=IP, transport=FakeTransport((200, body)))
    sessions = portal.sessions()
    assert len(sessions) == 1
    assert sessions[0].ip == IP
    assert sessions[0].time_long == "9"


def test_mine_matches_own_ip() -> None:
    body = f'cb({{"list":[{{"online_ip":"{IP}"}}]}})'
    portal = Portal(HUUC, timeout=1, retries=0, ip=IP, transport=FakeTransport((200, body)))
    assert portal.mine() is not None


def test_mine_ignores_other_ip() -> None:
    body = 'cb({"list":[{"online_ip":"10.9.9.9"}]})'
    portal = Portal(HUUC, timeout=1, retries=0, ip=IP, transport=FakeTransport((200, body)))
    assert portal.mine() is None


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


def test_logout_uses_logout_path() -> None:
    transport = FakeTransport((200, "{}"))
    portal = Portal(HUUC, timeout=1, retries=0, ip=IP, transport=transport)
    portal.logout()
    assert "/eportal/portal/logout" in transport.last_url


# ---------- 传输重试 ----------


def make_adaptive(mask: bool = True, transport=None, retries: int = 2) -> tuple[Portal, object]:
    portal = Portal(HUUC, timeout=1, retries=retries, ip=IP, transport=transport)  # type: ignore[arg-type]
    portal.mask_urls = mask
    return portal, transport


def test_request_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeTransport(
        TransportError("boom"), TransportError("boom"), (200, 'cb({"result":1})')
    )
    portal, _ = make_adaptive(transport=transport)
    assert portal.request(Request("/p")) == {"result": 1}
    assert len(transport.calls) == 3


def test_request_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeTransport(TransportError("down"), TransportError("down"))
    portal, _ = make_adaptive(transport=transport, retries=1)
    with pytest.raises(TransportError, match="请求失败"):
        portal.request(Request("/p"))
    assert len(transport.calls) == 2


def test_retry_after_seconds_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    transport = FakeTransport((429, "{}", {"Retry-After": "1"}), (200, '{"result":1}'))
    portal, _ = make_adaptive(transport=transport, retries=1)
    assert portal.request(Request("/p")) == {"result": 1}
    assert slept == [pytest.approx(1.0)]


def test_retry_after_http_date_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 也允许日期格式；以前 float() 直接吃不下，会抛 ValueError 变成退出码 70。"""
    when = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=3)
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    transport = FakeTransport(
        (503, "{}", {"Retry-After": email.utils.format_datetime(when)}), (200, '{"result":1}')
    )
    portal, _ = make_adaptive(transport=transport, retries=1)
    assert portal.request(Request("/p")) == {"result": 1}
    assert 1.5 < slept[0] <= 4.0


def test_retry_after_garbage_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    transport = FakeTransport((429, "{}", {"Retry-After": "不久之后"}), (200, '{"result":1}'))
    portal, _ = make_adaptive(transport=transport, retries=1)
    portal.request(Request("/p"))
    assert slept == [pytest.approx(2.0)]


def test_retry_after_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    transport = FakeTransport((429, "{}", {"Retry-After": "9999"}), (200, '{"result":1}'))
    portal, _ = make_adaptive(transport=transport, retries=1)
    portal.request(Request("/p"))
    assert slept == [pytest.approx(60.0)]


def test_html_200_is_parsed_as_failure_without_retrying() -> None:
    """回了个成功页 HTML 时，重发一遍也是一样的，别打三次。"""
    transport = FakeTransport((200, "<html>登录成功，欢迎</html>"))
    portal, _ = make_adaptive(transport=transport)
    with pytest.raises(ParseError):
        portal.request(Request("/p"))
    assert len(transport.calls) == 1


@pytest.mark.parametrize("code", [403, 500])
def test_error_status_with_json_body_is_still_failure(code: int) -> None:
    """错误页里也可能带 `{"result":0}`，不能因为含 { 就当成功。"""
    transport = FakeTransport((code, '{"result":0}'))
    portal, _ = make_adaptive(transport=transport, retries=0)
    with pytest.raises(TransportError, match=f"HTTP {code}"):
        portal.request(Request("/p"))


def test_request_error_masks_password_by_default() -> None:
    transport = FakeTransport(TransportError("down"))
    portal, _ = make_adaptive(transport=transport, retries=0)
    with pytest.raises(TransportError) as info:
        portal.request(Request("/p", params=[Param("user_password", "abcdefgh", encode=False)]))
    assert "user_password=ab…gh" in str(info.value)


def test_request_error_can_show_secrets() -> None:
    transport = FakeTransport(TransportError("down"))
    portal, _ = make_adaptive(mask=False, transport=transport, retries=0)
    with pytest.raises(TransportError) as info:
        portal.request(Request("/p", params=[Param("user_password", "abcdefgh", encode=False)]))
    assert "user_password=abcdefgh" in str(info.value)


def test_mask_url_hides_password_only() -> None:
    url = (
        "https://p/eportal/portal/login?user_account=3925&user_password=66707667&wlan_user_ip=2425"
    )
    masked = _mask_url(url)
    assert "user_password=66" in masked
    assert "66707667" not in masked
    assert "user_account=3925" in masked
    assert "wlan_user_ip=2425" in masked


def test_urllib_transport_maps_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """真 transport 要把 URLError 翻成 TransportError，Portal 才认。"""
    from campus_auth.transport import UrllibTransport

    transport = UrllibTransport()

    def boom(*_a, **_k):
        raise urllib.error.URLError("x")

    monkeypatch.setattr(transport._opener, "open", boom)
    with pytest.raises(TransportError):
        transport.send("http://1.2.3.4/")


def test_urllib_transport_returns_status_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth.transport import UrllibTransport

    class FakeResp:
        status = 200
        headers: dict[str, str] = {}

        def read(self, _limit: int = 0) -> bytes:
            return b'{"ok":1}'

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    transport = UrllibTransport()
    monkeypatch.setattr(transport._opener, "open", lambda *_a, **_k: FakeResp())
    response = transport.send("http://1.2.3.4/")
    assert response.status == 200 and response.text == '{"ok":1}'


def test_retry_delays_capped() -> None:
    delays = list(iter_retry_delays(10, base=1, cap=8))
    assert delays == sorted(delays)
    assert max(delays) <= 8
