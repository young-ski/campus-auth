"""河南城建学院（HUUC）适配层 —— UCLINK / UCSIG 门户。

协议来自门户前端 `a41.js` 的 `getkey` / `enc_pwd` 以及抓包核对：

* 密钥 = `wlan_user_ip` 各字符 ASCII 逐位异或
* 账号要带 `,0,` 前缀；宿舍（UCSIG）还要挂运营商后缀
* `wlan_user_mac` 服务端不校验，可填全 0
* 成功与否一律以 `online_list` 里出现自己的 IP 为准，别信 `msg`

宿舍联通/电信多数账号还没在运营商侧开通，现象是 `unbind isp uid` /
`AC认证失败` —— 那是运营商的问题，不是密码错。
"""

from __future__ import annotations

from ..adapters.base import Adapter, LoginResult
from ..crypto import xor_key

PORTAL_IP = "10.210.213.208"

# (区域说明, SSID, 建议后缀)
SSID_ZONES = {
    "UCLINK": ("教学楼/图书馆", "UCLINK", "none"),
    "UCSIG": ("宿舍", "UCSIG", "cmcc"),
}
SUBNET_ZONES = {
    "10.152.": ("教学楼/图书馆", "UCLINK", "none"),
    "10.138.": ("宿舍", "UCSIG", "cmcc"),
}

HINTS = {
    "unbind isp uid": "运营商侧还没绑定这个账号：宿舍请确认已开通宽带，或换 -w cmcc。",
    "AC认证失败": "AC 认证失败，多因运营商侧未开通或该 SSID 只收特定运营商。",
    "账号或密码错误": "账号或密码不对；账号是纯数字学号，不要带 @ 后缀（后缀由 -w 拼）。",
    "用户已在线": "已经在线了，直接跑 status 看看。",
    "没有可解析的 JSON": "门户回的是页面不是 JSON：确认 base_url 指到 eportal 入口，不是门户首页。",
}


class HuucAdapter(Adapter):
    def __init__(self) -> None:
        super().__init__(
            name="huuc",
            school="河南城建学院",
            base_url="https://netauth.huuc.edu.cn:802",
            key_style="ip-xor",
            account_prefix=",0,",
            operator_suffixes={"cmcc": "@cmcc", "unicom": "@unicom", "dx": "@dx"},
            js_version="4.2.1",
            notes=f"门户 IP {PORTAL_IP}；netauth.huuc.edu.cn:802。",
        )

    def zone_of(self, ip: str, ssid: str | None) -> tuple[str, str | None, str | None, str]:
        """(区域, SSID, 应选后缀, 依据)。依据是 ssid / subnet / none。"""
        if ssid and ssid in SSID_ZONES:
            return (*SSID_ZONES[ssid], "ssid")
        for prefix, info in SUBNET_ZONES.items():
            if ip.startswith(prefix):
                return (*info, "subnet")
        return ("未知", ssid, None, "none")

    def zone_hint(self, ip: str, ssid: str | None) -> str:
        area, seen, want, source = self.zone_of(ip, ssid)
        if want is None:
            return f"没认出所在区域（SSID {seen or '未知'}），如果在宿舍要手动加 -w cmcc。"
        if want == "none":
            return ""
        if want == "cmcc":
            return f"看着像{area}（{source}），宿舍一般要加 -w cmcc，否则多半 AC 认证失败。"
        return ""

    def hint_for(self, ret_code: int | None, msg: str) -> str:
        for needle, hint in HINTS.items():
            if needle in msg:
                return hint
        if "AC认证失败" in msg or "isp uid" in msg:
            return HINTS["AC认证失败"]
        return super().hint_for(ret_code, msg)

    def interpret_login(self, resp):
        result = super().interpret_login(resp)
        if not result.ok and not result.hint:
            result = LoginResult(False, result.msg, result.ret_code, "服务端拒绝但没给可读原因。")
        return result


ADAPTER = HuucAdapter()


def key_for(ip: str) -> int:
    """便于排查：直接看某个 IP 派生出的密钥。"""
    return xor_key(ip)
