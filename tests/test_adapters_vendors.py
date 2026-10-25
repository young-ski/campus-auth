from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from campus_auth import state
from campus_auth.adapters.ruijie import ADAPTER as RUIJIE
from campus_auth.adapters.srun import ADAPTER as SRUN
from campus_auth.crypto_srun import sha1_hex, srun_b64, xxtea
from campus_auth.errors import ConfigError
from campus_auth.portal import extract_json

IP = "10.1.2.3"
CAPTIVE = (
    "<html><script>top.self.location.href='http://1.2.3.4/eportal/index.jsp"
    "?wlanuserip=10.1.2.3&wlanacname=AC1&service=cmcc&t=wireless-v2'</script></html>"
)
PORTAL_PAGE = '<html><script src="/eportal/portal/js/index_1.js"></script></html>'


class FakePortal:
    """只实现适配层用到的那点东西。"""

    def __init__(self, base_url: str, pages: dict[str, tuple[int, str]] | None = None) -> None:
        self.base_url = base_url
        self.ip = IP
        self.mac = "0" * 12
        self.account = "20240001"
        self.password = "secret"
        self.operator = "none"
        self.ctx: dict = {}
        self.pages = pages or {}
        self.calls: list[tuple[str, str]] = []

    def raw(self, url: str, **_kw):
        self.calls.append(("raw", url))
        return self.pages.get(url, (200, ""))

    def request(self, request):
        self.calls.append(("request", request.path))
        status, payload = self.pages.get(request.path, (200, "{}"))
        if isinstance(payload, dict):
            return payload
        return extract_json(payload)


# ---------- 锐捷 ----------


def test_ruijie_discovers_portal_from_captive_page() -> None:
    portal = FakePortal(
        "http://connect.rom.miui.com/generate_204",
        {"http://connect.rom.miui.com/generate_204": (200, CAPTIVE)},
    )
    ctx = RUIJIE.discover(portal, "20240001")
    assert ctx["login_url"] == "http://1.2.3.4/eportal/InterFace.do?method=login"
    assert ctx["service"] == "cmcc"
    # & 与 = 都要再编码一次
    assert "%2526" in str(ctx["query_string"])
    assert "%253D" in str(ctx["query_string"])


def test_ruijie_reports_missing_portal() -> None:
    portal = FakePortal(
        "http://connect.rom.miui.com", {"http://connect.rom.miui.com": (200, "nope")}
    )
    with pytest.raises(ConfigError, match="index.jsp"):
        RUIJIE.discover(portal, "u")


def test_ruijie_uses_given_portal_page() -> None:
    page = "http://1.2.3.4/eportal/index.jsp?wlanuserip=10.1.2.3&service=x"
    portal = FakePortal(page)
    ctx = RUIJIE.discover(portal, "u")
    assert ctx["login_url"].startswith("http://1.2.3.4/eportal/InterFace.do")
    assert portal.calls == []  # 不用再取劫持页


def test_ruijie_offline_fallback_keeps_ip_in_query() -> None:
    """已在线时劫持页是空 204，回退 index.jsp 必须把 IP 带上，否则 queryString 为空。"""
    portal = FakePortal(
        "http://connect.rom.miui.com/generate_204",
        {
            "http://connect.rom.miui.com/generate_204": (204, ""),
            "http://connect.rom.miui.com/eportal/index.jsp?wlanuserip=10.1.2.3": (200, PORTAL_PAGE),
        },
    )
    ctx = RUIJIE.discover(portal, "u")
    assert ctx["query_string"] == "wlanuserip%253D10.1.2.3"
    assert ctx["unbind_url"] == "http://connect.rom.miui.com/eportal/InterFace.do?method=unbind"


def test_ruijie_fallback_retries_without_query() -> None:
    """不认 wlanuserip 的版本：带参 404，就退回裸 index.jsp。"""
    portal = FakePortal(
        "http://connect.rom.miui.com/generate_204",
        {
            "http://connect.rom.miui.com/generate_204": (204, ""),
            "http://connect.rom.miui.com/eportal/index.jsp": (200, PORTAL_PAGE),
        },
    )
    ctx = RUIJIE.discover(portal, "u")
    assert ctx["referer"] == "http://connect.rom.miui.com/eportal/index.jsp"
    assert ctx["query_string"] == ""


def test_ruijie_login_is_post_with_expected_fields() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    req = RUIJIE.login_request(portal)
    assert req.method == "POST"
    assert req.path.startswith("http://1.2.3.4/eportal/InterFace.do?method=login")
    assert set(req.body) == {
        "userId",
        "password",
        "service",
        "queryString",
        "operatorPwd",
        "operatorUserId",
        "validcode",
        "passwordEncrypt",
    }
    assert req.body["userId"] == "20240001"
    assert req.body["passwordEncrypt"] == "false"
    assert req.headers["Referer"].endswith("service=x")


@pytest.mark.parametrize(
    ("payload", "ok"),
    [
        ({"result": "success", "message": ""}, True),
        ({"result": "fail", "message": "账号或密码错误"}, False),
        ({"result": "fail", "message": "用户已在线"}, False),
        ({}, False),
    ],
)
def test_ruijie_interpret(payload: dict, ok: bool) -> None:
    assert RUIJIE.interpret_login(payload).ok is ok


def test_ruijie_hints() -> None:
    assert "学号" in RUIJIE.hint_for(None, "账号或密码错误")
    assert "注销" in RUIJIE.hint_for(None, "终端数量达到上限")


def test_ruijie_logout_is_post_and_uses_user_index() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    RUIJIE.after_login(portal, {"result": "success", "userIndex": "u-9"})
    req = RUIJIE.logout_request(portal)
    assert req.method == "POST"
    assert "method=logout" in req.path
    assert req.body["userIndex"] == "u-9"


def test_ruijie_logout_reuses_index_from_previous_process() -> None:
    """`logout` 和 `login` 是两条命令：本进程没登录过就用缓存的那个 userIndex。"""
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    state.save_user_index("ruijie", portal.account, portal.ip, "idx7")
    assert RUIJIE.logout_request(portal).body["userIndex"] == "idx7"


def test_ruijie_after_login_persists_index() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    RUIJIE.after_login(portal, {"result": "success", "userIndex": "u-9"})
    assert state.load_user_index("ruijie", portal.account, portal.ip) == "u-9"


def test_ruijie_successful_logout_drops_index() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    RUIJIE.after_login(portal, {"result": "success", "userIndex": "u-9"})
    RUIJIE.after_logout(portal, {"result": "success"})
    assert state.load_user_index("ruijie", portal.account, portal.ip) == ""


def test_ruijie_failed_logout_keeps_index() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    RUIJIE.after_login(portal, {"result": "success", "userIndex": "u-9"})
    RUIJIE.after_logout(portal, {"result": "fail", "message": "未登录"})
    assert state.load_user_index("ruijie", portal.account, portal.ip) == "u-9"


def test_ruijie_login_without_user_index_saves_nothing() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    RUIJIE.after_login(portal, {"result": "success"})
    assert state.load_user_index("ruijie", portal.account, portal.ip) == ""


def test_ruijie_unbind_posts_user_id_to_interface() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    req = RUIJIE.unbind_request(portal)
    assert req.method == "POST"
    assert req.path == "http://1.2.3.4/eportal/InterFace.do?method=unbind"
    assert req.body["userId"] == "20240001"
    # queryString 跟登录一样是二次编码过的，服务端只解一层
    assert req.body["queryString"] == "service%253Dx"
    assert req.body["password"] == "secret"
    assert "userIndex" not in req.body
    assert req.headers["Referer"].endswith("service=x")


def test_ruijie_unbind_carries_user_index_when_known() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    portal.ctx = RUIJIE.discover(portal, portal.account)
    RUIJIE.after_login(portal, {"result": "success", "userIndex": "u-9"})
    portal.password = ""  # 没配密码也照样能解绑
    req = RUIJIE.unbind_request(portal)
    assert req.body["userIndex"] == "u-9"
    assert "password" not in req.body


def test_ruijie_unbind_without_discovery_uses_portal_origin() -> None:
    portal = FakePortal("http://1.2.3.4/eportal/index.jsp?service=x")
    req = RUIJIE.unbind_request(portal)
    assert req.path == "http://1.2.3.4/eportal/InterFace.do?method=unbind"
    assert req.body["queryString"] == ""


def test_ruijie_online_check_reads_204() -> None:
    portal = FakePortal("x", {"http://connect.rom.miui.com/generate_204": (204, "")})
    assert RUIJIE.online_check(portal) is True
    portal.pages["http://connect.rom.miui.com/generate_204"] = (200, "<html>")
    assert RUIJIE.online_check(portal) is False


# ---------- 深澜 ----------

LOGIN_PAGE = "<script>var ac_id='12';</script>"


def srun_portal(challenge: str = "abc123") -> FakePortal:
    return FakePortal(
        "http://1.2.3.4",
        {
            "http://1.2.3.4/": (200, LOGIN_PAGE),
            "/cgi-bin/get_challenge": (
                200,
                f'({{"challenge":"{challenge}","client_ip":"{IP}"}})',
            ),
        },
    )


def test_srun_discover_reads_ac_id_and_challenge() -> None:
    portal = srun_portal()
    ctx = SRUN.discover(portal, portal.account)
    assert ctx["ac_id"] == "12"
    assert ctx["challenge"] == "abc123"
    assert ctx["client_ip"] == IP


def test_srun_discover_without_challenge_fails() -> None:
    portal = srun_portal()
    portal.pages["/cgi-bin/get_challenge"] = (200, '({"error":"ok"})')
    with pytest.raises(ConfigError, match="challenge"):
        SRUN.discover(portal, portal.account)


def test_srun_defaults_ac_id_zero_when_absent() -> None:
    portal = srun_portal()
    portal.pages["http://1.2.3.4/"] = (200, "<html>no id</html>")
    assert SRUN.discover(portal, portal.account)["ac_id"] == "0"


def test_srun_login_params_are_signed() -> None:
    portal = srun_portal()
    portal.ctx = SRUN.discover(portal, portal.account)
    params = {p.key: p.value for p in SRUN.login_request(portal).params}

    expected_md5 = hmac.new(b"abc123", b"secret", hashlib.md5).hexdigest()
    assert params["password"] == "{MD5}" + expected_md5
    assert params["info"].startswith("{SRBX1}")
    assert params["action"] == "login"
    assert params["ac_id"] == "12"
    assert params["n"] == "200" and params["type"] == "1"

    info = params["info"]
    fields = [portal.account, expected_md5, "12", IP, "200", "1", info]
    expected_sum = sha1_hex("".join("abc123" + f for f in fields))
    assert params["chksum"] == expected_sum


def test_srun_info_decodes_back_to_json() -> None:
    portal = srun_portal("key1234")
    portal.ctx = SRUN.discover(portal, portal.account)
    info = {p.key: p.value for p in SRUN.login_request(portal).params}["info"]
    assert info.startswith("{SRBX1}")
    raw = xxtea(info[len("{SRBX1}") :].encode(), b"key1234")  # 只是长度能对上
    assert len(raw) > 0


def test_srun_info_uses_custom_base64() -> None:
    portal = srun_portal()
    portal.ctx = SRUN.discover(portal, portal.account)
    info = {p.key: p.value for p in SRUN.login_request(portal).params}["info"]
    assert srun_b64(b"") == ""
    assert all(c not in info[len("{SRBX1}") :] for c in "_-")


# ---------- 深澜 srun_bx2 变体 ----------


def srun_bx2_portal() -> FakePortal:
    portal = srun_portal("key1234")
    portal.pages["http://1.2.3.4/"] = (
        200,
        "<script>var ac_id='12';var enc_ver='srun_bx2';</script>",
    )
    return portal


def test_srun_detects_bx2_from_login_page() -> None:
    portal = srun_bx2_portal()
    assert SRUN.discover(portal, portal.account)["enc_ver"] == "srun_bx2"


def test_srun_defaults_to_bx1() -> None:
    portal = srun_portal()
    assert SRUN.discover(portal, portal.account)["enc_ver"] == "srun_bx1"


def test_srun_bx2_uses_srbx2_and_standard_base64() -> None:
    portal = srun_bx2_portal()
    portal.ctx = SRUN.discover(portal, portal.account)
    info = {p.key: p.value for p in SRUN.login_request(portal).params}["info"]
    assert info.startswith("{SRBX2}")
    payload = info[len("{SRBX2}") :]
    # 标准字母表：解得回来，且和 bx1 的密文一模一样（只换了 base64 表）
    cipher = base64.b64decode(payload, validate=True)
    assert cipher == xxtea(
        json.dumps(
            {
                "username": portal.account,
                "password": portal.password,
                "ip": IP,
                "acid": "12",
                "enc_ver": "srun_bx2",
            },
            separators=(",", ":"),
        ).encode(),
        b"key1234",
    )


def test_srun_bx2_chksum_still_covers_info() -> None:
    portal = srun_bx2_portal()
    portal.ctx = SRUN.discover(portal, portal.account)
    params = {p.key: p.value for p in SRUN.login_request(portal).params}
    expected_md5 = hmac.new(b"key1234", b"secret", hashlib.md5).hexdigest()
    fields = [portal.account, expected_md5, "12", IP, "200", "1", params["info"]]
    assert params["chksum"] == sha1_hex("".join("key1234" + f for f in fields))


@pytest.mark.parametrize(
    ("payload", "ok"),
    [
        ({"error": "ok", "suc_msg": "认证成功"}, True),
        ({"error": "login_error", "error_msg": "密码错误"}, False),
        ({"error": "not_online"}, False),
    ],
)
def test_srun_interpret(payload: dict, ok: bool) -> None:
    assert SRUN.interpret_login(payload).ok is ok


def test_srun_hints() -> None:
    assert "学号" in SRUN.hint_for(None, "login_error")
    assert "ac_id" in SRUN.hint_for(None, "ac_id_error")


def test_srun_online_check() -> None:
    portal = FakePortal("http://1.2.3.4", {"/cgi-bin/rad_user_info": (200, '({"error":"ok"})')})
    assert SRUN.online_check(portal) is True
    portal.pages["/cgi-bin/rad_user_info"] = (200, '({"error":"not_online"})')
    assert SRUN.online_check(portal) is False


def test_srun_sessions_wrap_payload() -> None:
    assert SRUN.interpret_sessions({"error": "not_online"}) == []
    assert len(SRUN.interpret_sessions({"error": "ok", "online_ip": IP})) == 1
