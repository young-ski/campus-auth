"""适配层基类。

一个适配层只描述"某所学校门户的差异"，不实现 HTTP、重试、CLI。
差异面被压缩成四件事：

1. `base_url` 与各接口路径
2. 密钥怎么来、参数怎么编码（`key_style` + `encoder`）
3. 账号怎么拼（前缀、运营商后缀）
4. 响应怎么解读（`interpret_login`）、在线列表怎么认人

新增一所学校 = 抄一份 `example_generic.py` 改常量，别动 core。
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ..crypto import xor_hex, xor_key

__all__ = ["Adapter", "Param", "LoginResult"]


class Param(tuple):
    """一个查询参数: (键, 明文值, 是否参与编码)。"""

    def __new__(cls, key: str, value: str, encode: bool = True) -> Param:
        return super().__new__(cls, (key, value, encode))

    key = property(lambda self: self[0])
    value = property(lambda self: self[1])
    encode = property(lambda self: self[2])


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    msg: str
    ret_code: int | None = None
    hint: str = ""


Encoder = Callable[[str], str]


@dataclass(frozen=True)
class Adapter:
    name: str
    school: str
    base_url: str
    key_style: str = "ip-xor"
    account_prefix: str = ""
    account_delimiter: str = ","
    operator_suffixes: Mapping[str, str] = field(default_factory=dict)
    js_version: str = ""
    login_path: str = "/eportal/portal/login"
    logout_path: str = "/eportal/portal/logout"
    unbind_path: str = "/eportal/portal/mac/unbind"
    online_path: str = "/eportal/portal/online_list"
    callback_prefix: str = "dr"
    timeout: float = 20.0
    verify_tls: bool = False
    notes: str = ""

    # ---------- 编码 ----------

    def encoder(self, ip: str) -> Encoder:
        """返回一个把明文变密文的函数。"""
        if self.key_style == "plain":
            return lambda text: text
        if self.key_style == "ip-xor":
            key = xor_key(ip)
            return lambda text: xor_hex(text, key)
        raise ValueError(f"未知 key_style: {self.key_style}")

    # ---------- 账号 ----------

    def format_account(self, account: str, operator: str = "none") -> str:
        suffix = self.operator_suffixes.get(operator, "") if operator else ""
        return f"{self.account_prefix}{account}{suffix}"

    def operator_names(self) -> list[str]:
        return ["none", *self.operator_suffixes]

    # ---------- 参数 ----------

    def callback(self, action: str) -> str:
        return f"{self.callback_prefix}{action}"

    def account_params(self, account: str, password: str, operator: str) -> list[Param]:
        return [
            Param("user_account", self.format_account(account, operator)),
            Param("user_password", password),
        ]

    def identity_params(self, ip: str, mac: str, cb: str) -> list[Param]:
        """每个请求都带的身份参数；`wlan_ac_ip` 等手段留空。"""
        params = [
            Param("wlan_user_ip", ip),
            Param("wlan_user_ipv6", "", encode=False),
            Param("wlan_user_mac", mac),
            Param("wlan_ac_ip", "", encode=False),
            Param("wlan_ac_name", "", encode=False),
        ]
        if self.js_version:
            params.append(Param("jsVersion", self.js_version))
        params += [
            Param("captcha", "", encode=False),
            Param("terminal_type", "1"),
            Param("lang", "zh"),
            Param("encrypt", "1", encode=False),
            Param("v", self.nonce(), encode=False),
            Param("lang", "zh", encode=False),  # 前端确实发了两次 lang
        ]
        return params

    @staticmethod
    def nonce() -> str:
        return f"0.{random.randint(10**15, 10**16 - 1)}"

    def login_params(
        self, *, ip: str, mac: str, account: str, password: str, operator: str
    ) -> list[Param]:
        cb = self.callback("1003")
        return [
            Param("callback", cb),
            Param("login_method", "1"),
            *self.account_params(account, password, operator),
            *self.identity_params(ip, mac, cb),
        ]

    def logout_params(self, *, ip: str, mac: str) -> list[Param]:
        cb = self.callback("1004")
        return [
            Param("callback", cb),
            Param("login_method", "1"),
            Param("user_account", "drcom"),
            Param("user_password", "123"),
            Param("ac_logout", "1"),
            Param("register_mode", "1"),
            Param("wlan_vlan_id", "0"),
            *self.identity_params(ip, mac, cb),
        ]

    def unbind_params(self, *, ip: str, mac: str, account: str) -> list[Param]:
        params = [
            Param("callback", self.callback("1005")),
            Param("user_account", account),
            Param("wlan_user_mac", mac),
            Param("wlan_user_ip", ip),
        ]
        if self.js_version:
            params.append(Param("jsVersion", self.js_version))
        params += [
            Param("encrypt", "1", encode=False),
            Param("v", self.nonce(), encode=False),
            Param("lang", "zh"),
            Param("lang", "zh", encode=False),
        ]
        return params

    def online_params(self) -> list[Param]:
        return [Param("callback", "cb", encode=False), Param("lang", "zh", encode=False)]

    # ---------- 响应解读 ----------

    def interpret_login(self, resp: Mapping[str, object]) -> LoginResult:
        code = resp.get("ret_code")
        ret_code = (
            int(code) if isinstance(code, int | str) and str(code).lstrip("-").isdigit() else None
        )
        msg = str(resp.get("msg") or "")
        ok = resp.get("result") in (1, "1", True) and ret_code in (0, None)
        return LoginResult(ok=ok, msg=msg, ret_code=ret_code, hint=self.hint_for(ret_code, msg))

    def hint_for(self, ret_code: int | None, msg: str) -> str:
        """把服务端的含糊报错翻译成人话；子类按需覆盖。"""
        if ret_code in (0, None):
            return ""
        return f"服务端返回 ret_code={ret_code}，原文: {msg or '(空)'}"

    def row_is_mine(self, row: Mapping[str, object], ip: str, mac: str) -> bool:
        return str(row.get("online_ip") or "") == ip

    def zone_hint(self, ip: str, ssid: str | None) -> str:
        return ""

    # ---------- 自检 ----------

    def check(self) -> None:
        if self.key_style not in {"plain", "ip-xor"}:
            raise ValueError(f"{self.name}: 未知 key_style {self.key_style!r}")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError(f"{self.name}: base_url 必须以 http(s):// 开头")
