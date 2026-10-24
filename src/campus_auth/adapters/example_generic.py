"""通用 eportal 适配层模板 —— 抄这份改成你的学校。

适用面：走 `/eportal/portal/login` 的 Dr.COM 门户，**且不校验加密**（`encrypt=1`
但没有异或层，或服务端宽松）。真机一跑就报错的话，按下面顺序核对：

1. 浏览器 F12 → Network，点一次登录，看实际请求的 URL 和参数名。
   参数名不同就覆盖 `login_params()`。
2. 参数值全是 `%xx` 十六进制 → 改用 `key_style="ip-xor"`，并在
   `encoder()` 里换成你学校的密钥算法（常见是网卡 MAC 或固定盐）。
3. 响应不是 JSON → 覆盖 `interpret_login()`。
4. 路径不同（有的在 `/eportal/portal/login`，有的带随机前缀）→ 改路径字段。
"""

from __future__ import annotations

from .base import Adapter

ADAPTER = Adapter(
    name="generic",
    school="未具名学校（模板）",
    base_url="http://10.0.0.1:8080",
    key_style="plain",
    account_prefix=",0,",
    operator_suffixes={},
    js_version="4.2.1",
    notes="改 base_url 和各路径后先跑 `campus-auth status` 验证能不能连通。",
)
