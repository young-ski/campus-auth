"""深澜（Srun）适配层。

流程比另外两套都绕，但每一步都是必须的：

1. `get_challenge` 拿一次性 challenge（也顺便带出服务端看到的 `client_ip`）
2. `password` 传 `{MD5}` + hmac_md5(challenge, 密码)
3. `info` 传 `{SRBX1}` + XXTEA(json) 的深澜 base64
4. `chksum` 用 sha1 把上面这些按固定顺序拼起来签名，服务端校验
5. 在线与否看 `rad_user_info` 的 `error` 字段

`ac_id` 各校不同，从登录页里的 `ac_id` 常量读；读不到给 "0"（不少学校就是 0）。

`enc_ver` 有两代：`srun_bx1`（深澜自家 base64 字母表）和 `srun_bx2`（标准 base64，
前缀 `{SRBX2}`）。从登录页脚本里的 `enc_ver` 认，认不出按 `srun_bx1`。

状态：**未实机验证**。算法对照 vidar-team/srun-login 实现并用其向量钉住，
但各校 Srun 版本差异大（`srun_bx1` / `srun_bx2`），跑不通请开 Issue 带打码样本。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from ..crypto_srun import hmac_md5_hex, sha1_hex, srun_b64, srun_b64_std, xxtea
from ..errors import ConfigError
from .base import Adapter, LoginResult, Param, Request

_AC_ID = re.compile(r"""ac_id["'\s:=]+\s*["']?(\d+)""", re.IGNORECASE)
_ENC_VER = re.compile(r"""srun_bx[12]""", re.IGNORECASE)
_N, _TYPE = "200", "1"

# 变体 -> (info 前缀, base64 编码器)。`enc_ver` 本来就是变体名，直接当键用。
VARIANTS: dict[str, tuple[str, Callable[[bytes], str]]] = {
    "srun_bx1": ("{SRBX1}", srun_b64),
    "srun_bx2": ("{SRBX2}", srun_b64_std),
}
DEFAULT_VARIANT = "srun_bx1"

HINTS = {
    "login_error": "账号或密码不对；深澜的账号通常是学号。",
    "user_already_online": "已经在线。",
    "ip_already_online": "这个 IP 已经有会话了，先注销。",
    "ac_id_error": "ac_id 不对：用 --url 指向真实的登录页，别只给域名。",
    "challenge_expired": "challenge 过期了，重跑一次即可。",
    # 解绑打到 eportal 通用路径上只会拿回登录页 HTML
    "没有可解析的 JSON": "深澜没有解绑接口：改用 logout；只是换了设备就去门户页面手动解绑。",
}


class SrunAdapter(Adapter):
    def __init__(self) -> None:
        super().__init__(
            name="srun",
            school="深澜 Srun（通用）",
            base_url="http://10.0.0.1",
            key_style="plain",
            status="未实机",
            notes="必须 --url 指向校园网登录页（ac_id 与 enc_ver 从页面里读）。",
            logout_needs_password=True,  # 注销也要 chksum，密码少不得
        )

    # ---------- 发现 ----------

    def discover(self, portal, account: str) -> dict[str, object]:
        status, page = portal.raw(portal.base_url.rstrip("/") + "/")
        if status >= 400:
            raise ConfigError(f"取登录页失败（HTTP {status}）：确认 --url 指到了校园网门户")
        match = _AC_ID.search(page)
        ac_id = match.group(1) if match else "0"
        found = _ENC_VER.search(page)
        enc_ver = found.group(0).lower() if found else DEFAULT_VARIANT

        payload = portal.request(
            Request(
                path="/cgi-bin/get_challenge",
                params=[
                    Param("callback", "_", encode=False),
                    Param("username", account, encode=False),
                    Param("ip", portal.ip, encode=False),
                ],
            )
        )
        challenge = str(payload.get("challenge") or "")
        if not challenge:
            raise ConfigError(f"get_challenge 没给 challenge: {payload}")
        client_ip = str(payload.get("client_ip") or portal.ip)
        return {"challenge": challenge, "client_ip": client_ip, "ac_id": ac_id, "enc_ver": enc_ver}

    # ---------- 登录 ----------

    def _hmd5(self, portal) -> str:
        return hmac_md5_hex(portal.password, str(portal.ctx["challenge"]))

    def _variant(self, portal) -> tuple[str, str, Callable[[bytes], str]]:
        """返回 (enc_ver, info 前缀, base64 编码器)。认不出的变体按 bx1 走。"""
        enc_ver = str(portal.ctx.get("enc_ver") or DEFAULT_VARIANT)
        prefix, encode = VARIANTS.get(enc_ver, VARIANTS[DEFAULT_VARIANT])
        return enc_ver, prefix, encode

    def _info(self, portal) -> str:
        enc_ver, prefix, encode = self._variant(portal)
        info = {
            "username": portal.account,
            "password": portal.password,
            "ip": str(portal.ctx["client_ip"]),
            "acid": str(portal.ctx["ac_id"]),
            "enc_ver": enc_ver,
        }
        blob = xxtea(
            json.dumps(info, separators=(",", ":")).encode(), str(portal.ctx["challenge"]).encode()
        )
        return prefix + encode(blob)

    def _chksum(self, portal, info: str) -> str:
        challenge = str(portal.ctx["challenge"])
        fields = [
            portal.account,
            self._hmd5(portal),
            str(portal.ctx["ac_id"]),
            str(portal.ctx["client_ip"]),
            _N,
            _TYPE,
            info,
        ]
        return sha1_hex("".join(challenge + field for field in fields))

    def login_request(self, portal) -> Request:
        info = self._info(portal)
        return Request(
            path="/cgi-bin/srun_portal",
            params=[
                Param("callback", "_", encode=False),
                Param("action", "login", encode=False),
                Param("username", portal.account, encode=False),
                Param("password", "{MD5}" + self._hmd5(portal), encode=False),
                Param("os", "Windows 10", encode=False),
                Param("name", "Windows", encode=False),
                Param("double_stack", "0", encode=False),
                Param("info", info, encode=False),
                Param("chksum", self._chksum(portal, info), encode=False),
                Param("ac_id", str(portal.ctx["ac_id"]), encode=False),
                Param("ip", str(portal.ctx["client_ip"]), encode=False),
                Param("n", _N, encode=False),
                Param("type", _TYPE, encode=False),
            ],
        )

    def logout_request(self, portal) -> Request:
        info = self._info(portal)
        return Request(
            path="/cgi-bin/srun_portal",
            params=[
                Param("callback", "_", encode=False),
                Param("action", "logout", encode=False),
                Param("username", portal.account, encode=False),
                Param("ac_id", str(portal.ctx.get("ac_id") or "0"), encode=False),
                Param("ip", str(portal.ctx.get("client_ip") or portal.ip), encode=False),
                Param("chksum", self._chksum(portal, info), encode=False),
            ],
        )

    # ---------- 解读 ----------

    def interpret_login(self, resp) -> LoginResult:
        error = str(resp.get("error") or "")
        ok = error.lower() == "ok"
        message = str(resp.get("suc_msg") or resp.get("error_msg") or error)
        hint = "" if ok else self.hint_for(None, error)
        return LoginResult(ok=ok, msg=message, ret_code=None, hint=hint)

    def hint_for(self, ret_code: int | None, msg: str) -> str:
        for needle, hint in HINTS.items():
            if needle in msg:
                return hint
        return f"服务端返回 error={msg or '(空)'}；见 README 的「已知限制」。"

    # ---------- 在线 ----------

    def online_check(self, portal) -> bool | None:
        payload = portal.request(
            Request(
                path="/cgi-bin/rad_user_info",
                params=[Param("callback", "_", encode=False)],
            )
        )
        return str(payload.get("error") or "").lower() == "ok"

    def sessions_request(self, portal) -> Request:
        return Request(
            path="/cgi-bin/rad_user_info",
            params=[Param("callback", "_", encode=False)],
        )

    def interpret_sessions(self, payload):
        if str(payload.get("error") or "").lower() != "ok":
            return []
        return [payload]


ADAPTER = SrunAdapter()
