"""Dr.COM / eportal 门户的编码原语。

前端的 `enc_pwd` 与 `getkey` 并不使用随机密钥：密钥是 `wlan_user_ip`
字符串中每个字符的 ASCII 码逐位异或的结果。于是

    key = xor_key(ip)

之后每个参数值都写成 `hex(ord(ch) ^ key)` 两位补零。IP 一变（DHCP 续租、
换楼、换网段）密钥就变，旧的登录 URL 随即失效 —— 这是必须跑客户端、
而不是点快捷方式的根本原因。
"""

from __future__ import annotations

__all__ = ["xor_key", "xor_hex", "xor_unhex", "HEX_WIDTH"]


def xor_key(text: str) -> int:
    """返回字符串的异或密钥；空串得 0。"""
    key = 0
    for ch in text:
        key ^= ord(ch)
    return key


HEX_WIDTH = 2


def xor_hex(text: str, key: int) -> str:
    """把 `text` 用 `key` 做异或并转成小写十六进制串。"""
    return "".join(f"{ord(ch) ^ key:0{HEX_WIDTH}x}" for ch in text)


def xor_unhex(data: str, key: int) -> str:
    """`xor_hex` 的逆运算，主要供测试和排查使用。"""
    if len(data) % HEX_WIDTH:
        raise ValueError(f"十六进制长度不是 {HEX_WIDTH} 的倍数: {data!r}")
    return "".join(
        chr(int(data[i : i + HEX_WIDTH], 16) ^ key) for i in range(0, len(data), HEX_WIDTH)
    )
