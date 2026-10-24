from __future__ import annotations

import pytest

from campus_auth.adapters import get_adapter, names
from campus_auth.adapters.base import Adapter
from campus_auth.adapters.huuc import ADAPTER as HUUC
from campus_auth.crypto import xor_unhex

IP = "10.152.59.163"


def test_builtin_registry() -> None:
    assert {"huuc", "generic"} <= set(names())
    assert get_adapter("huuc") is HUUC


def test_unknown_adapter() -> None:
    with pytest.raises(Exception, match="没有适配层"):
        get_adapter("nope")


def test_dynamic_target_requires_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "campus_auth.adapters.importlib.import_module",
        lambda name: type("M", (), {"ADAPTER": "not-an-adapter"})(),
    )
    with pytest.raises(Exception, match="不是 Adapter 实例"):
        get_adapter("m:ADAPTER")


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("none", ",0,081425412"),
        ("cmcc", ",0,081425412@cmcc"),
        ("unicom", ",0,081425412@unicom"),
        ("dx", ",0,081425412@dx"),
        ("", ",0,081425412"),
    ],
)
def test_format_account(operator: str, expected: str) -> None:
    assert HUUC.format_account("081425412", operator) == expected


def test_operator_names() -> None:
    assert HUUC.operator_names() == ["none", "cmcc", "unicom", "dx"]


def test_encoder_roundtrip() -> None:
    enc = HUUC.encoder(IP)
    assert xor_unhex(enc("081425412"), 0x21) == "081425412"


def test_generic_encoder_is_identity() -> None:
    assert get_adapter("generic").encoder(IP)("abc") == "abc"


def test_login_params_shape() -> None:
    params = HUUC.login_params(
        ip=IP, mac="0" * 12, account="081425412", password="pw", operator="cmcc"
    )
    keys = [p.key for p in params]

    assert keys[:4] == ["callback", "login_method", "user_account", "user_password"]
    assert keys.count("lang") == 2
    encoded = {p.key: p.encode for p in params}
    assert encoded["encrypt"] is False
    assert encoded["v"] is False
    assert encoded["callback"] is True
    assert encoded["user_account"] is True


def test_login_params_js_version_present() -> None:
    params = HUUC.login_params(ip=IP, mac="0" * 12, account="1", password="p", operator="none")
    assert ("jsVersion", "4.2.1") in [(p.key, p.value) for p in params]


def test_noncelooked_different() -> None:
    assert HUUC.nonce() != HUUC.nonce()


def test_logout_and_unbind_shape() -> None:
    logout = dict((p.key, p.value) for p in HUUC.logout_params(ip=IP, mac="A" * 12))
    assert logout["user_account"] == "drcom"
    assert logout["ac_logout"] == "1"

    unbind = dict((p.key, p.value) for p in HUUC.unbind_params(ip=IP, mac="A" * 12, account="1"))
    assert unbind["user_account"] == "1"


@pytest.mark.parametrize(
    ("payload", "ok"),
    [
        ({"result": 1, "ret_code": 0, "msg": ""}, True),
        ({"result": 1, "msg": "ok"}, True),
        ({"result": 0, "ret_code": 1, "msg": "unbind isp uid"}, False),
        ({"result": 1, "ret_code": 1, "msg": "AC认证失败"}, False),
        ({"result": 1, "ret_code": 1, "msg": "账号或密码错误"}, False),
    ],
)
def test_interpret_login(payload: dict, ok: bool) -> None:
    assert HUUC.interpret_login(payload).ok is ok


@pytest.mark.parametrize(
    ("msg", "needle"),
    [
        ("unbind isp uid", "运营商侧"),
        ("AC认证失败", "AC 认证失败"),
        ("账号或密码错误", "密码"),
    ],
)
def test_hints_are_actionable(msg: str, needle: str) -> None:
    assert needle in HUUC.hint_for(1, msg)


def test_generic_hint_mentions_ret_code() -> None:
    assert "ret_code=7" in get_adapter("generic").hint_for(7, "boom")


@pytest.mark.parametrize(
    ("ip", "ssid", "zone"),
    [
        ("10.138.1.2", "UCSIG", "宿舍"),
        ("10.152.1.2", None, "教学楼/图书馆"),
        ("10.138.1.2", "UCLINK", "教学楼/图书馆"),  # SSID 优先于网段
        ("172.16.0.1", "random", "未知"),
    ],
)
def test_zone_of(ip: str, ssid: str | None, zone: str) -> None:
    assert HUUC.zone_of(ip, ssid)[0] == zone


def test_zone_hint_for_dormitory() -> None:
    assert "cmcc" in HUUC.zone_hint("10.138.1.2", "UCSIG")


def test_zone_hint_teaching_building_silent() -> None:
    assert HUUC.zone_hint("10.152.1.2", "UCLINK") == ""


def test_zone_hint_unknown() -> None:
    assert "-w cmcc" in HUUC.zone_hint("172.16.0.1", None)


def test_check_rejects_bad_key_style() -> None:
    bad = Adapter(name="bad", school="x", base_url="http://x", key_style="rot13")
    with pytest.raises(ValueError, match="key_style"):
        bad.check()


def test_row_is_mine_by_ip() -> None:
    assert HUUC.row_is_mine({"online_ip": IP}, IP, "0" * 12)
    assert not HUUC.row_is_mine({"online_ip": "10.0.0.1"}, IP, "0" * 12)
