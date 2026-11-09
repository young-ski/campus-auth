# 非 ASCII 密码会发出去一份与浏览器不同的密文

- 级别：S3 · 成本：半天 · 标签：`bug` `crypto` `good first issue`
- 落点：`src/campus_auth/crypto.py:31`（`%02x` 宽度假设）、`src/campus_auth/config.py:60-81`（`validate`）

## 现象

```python
"".join(f"{ord(ch) ^ key:0{HEX_WIDTH}x}" for ch in text)
```

假设每个字符异或后 ≤ 0xFF，即恒为 2 位。用 `密码123` 这类非 ASCII 密码时：

- `ord(ch) ^ key` 可能远大于 255（`密码123` 的 key 为 `0x23f7`）；
- 值变 4 位十六进制，**长度不再对齐**，服务端按 2 位切分即错位；
- `xor_unhex(xor_hex(p, k)) != p`，本机往返都不成立。

关键背景：真实前端只对 ASCII 字符取 `charCode`，所以就算本机「看起来拼出来了」，发出去的密文与浏览器抓到的也不一致 —— 这是静默错误，不是崩。

## 复现

```bash
python -c "
from campus_auth.crypto import xor_key, xor_hex, xor_unhex
pw, k = '密码123', xor_key('10.1.2.3')
h = xor_hex(pw, k)
print(len(h), len(pw)*2, xor_unhex(h, k) == pw)
"
# 14 12 False
```

## 期望（二选一，推荐 1）

1. **挡住**：`Config.validate()` 里 `password.isascii()` 为假直接 `ConfigError`，文案指向「密码先改成 ASCII / 若必须中文见 #x」。
2. **支持**：按 UTF-8 字节做异或（每字节 2 位），并同步 `xor_unhex` 与假门户的解码。

推荐先 1 后 2：1 只要几行，2 需要真机比对。

## 失败断言

- 非 ASCII 密码在 `login` 前就被拦，exit 2，文案含「ASCII」。
- 若走方案 2：`xor_unhex(xor_hex(p, k), k).encode() == p.encode('utf-8')` 且长度为 `2 * len(p.encode())`。

## 验收

- 断言先红后绿。
- ASCII 密码的既有用例（`tests/test_crypto.py`）全部不变。

## 边界

- 只影响密码字段；账号、IP 一直要求 ASCII。
- 假门户（`tools/fake_portal.py`）会真解一遍密码，方案 2 必须同步改它，否则本地 e2e 会假绿。
