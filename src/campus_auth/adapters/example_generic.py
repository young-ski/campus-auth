"""通用 eportal 适配层模板 —— 抄这份改成你的学校。

**先跑 `campus-auth probe --url <门户地址>` 确认是 Dr.COM**，判成别的就别往下写。

改的时候按这个顺序核对（F12 → Network，作为普通用户点一次登录）：

1. 参数名不同 → 覆盖 `account_params()` / `identity_params()` 或整个 `login_request()`。
2. 参数值是 `%xx` 十六进制 → `key_style="ip-xor"`，并把密钥算法写进 `encoder()` 的
   返回函数（常见是 MAC 或固定盐，密钥一致才有用）。
3. 响应不是 JSON → 覆盖 `interpret_login()` 和 `hint_for()`。
4. 路径不同 → 改 `login_path` / `logout_path` 这些字段。

改完在 `adapters/__init__.py` 的 `BUILTIN` 登记，再跑
`campus-auth status --adapter <代号>` 和一次真机 `login`。
"""

from __future__ import annotations

from .base import Adapter


class GenericAdapter(Adapter):
    def __init__(self) -> None:
        super().__init__(
            name="generic",
            school="未具名学校（模板）",
            base_url="http://10.0.0.1:8080",
            key_style="plain",
            account_prefix=",0,",
            operator_suffixes={},
            js_version="4.2.1",
            status="模板",
            notes="改 base_url 和各路径后先跑 `campus-auth status` 验证能不能连通。",
        )


ADAPTER = GenericAdapter()
