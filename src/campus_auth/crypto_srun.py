"""深澜（Srun）登录要用的加密原语。

跟 Dr.COM 那套"异或一下"完全不是一回事：

* `info` 字段 = XXTEA(json, challenge) 再走深澜自带字母表的 base64，前面挂 `{SRBX1}`
* `password` 字段 = `{MD5}` + hmac_md5(key=challenge, msg=密码)
* `chksum` = sha1(challenge + 用户名 + 上面那个 md5 + ac_id + ip + n + type + info)

XXTEA 的实现对照 vidar-team/srun-login 的 Go 版逐行移植，并用它的测试向量
（`Encode("aaaaaaaaaaaa", "bbbbbbbbbbbb")`）钉住，别随手改。
"""

from __future__ import annotations

import base64
import hashlib
import hmac

__all__ = ["xxtea", "srun_b64", "hmac_md5_hex", "sha1_hex", "SRUN_ALPHA"]

_MASK = 0xFFFFFFFF
_DELTA = 0x9E3779B9

STD_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
SRUN_ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
_XLATE = str.maketrans(STD_ALPHA, SRUN_ALPHA)


def _at(data: bytes, i: int) -> int:
    return data[i] if i < len(data) else 0


def _pack(content: bytes, with_len: bool) -> list[int]:
    words = [
        _at(content, i)
        | _at(content, i + 1) << 8
        | _at(content, i + 2) << 16
        | _at(content, i + 3) << 24
        for i in range(0, len(content), 4)
    ]
    if with_len:
        words.append(len(content))
    return words


def _unpack(words: list[int], with_len: bool) -> bytes:
    out = bytearray()
    for word in words:
        out += bytes((word & 0xFF, word >> 8 & 0xFF, word >> 16 & 0xFF, word >> 24 & 0xFF))
    return bytes(out[: words[-1]]) if with_len else bytes(out)


def _round(z: int, y: int, s: int, k: int) -> int:
    mx = (((z >> 5) ^ (y << 2) & _MASK) + (((y >> 3) ^ (z << 4) & _MASK) ^ (s ^ y)) & _MASK) & _MASK
    return (mx + (k ^ z)) & _MASK


def xxtea(content: bytes, key: bytes) -> bytes:
    """XXTEA 加密（深澜用的变体，含它自己的加法掩码）。"""
    if not content:
        return b""
    v = _pack(content, True)
    k = _pack(key, False)
    while len(k) < 4:
        k.append(0)

    n = len(v) - 1
    z, y = v[n], v[0]
    q = 6 + 52 // (n + 1)
    total = 0
    while q > 0:
        total = (total + _DELTA) & _MASK
        e = (total >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            v[p] = (v[p] + _round(z, y, total, k[(p & 3) ^ e])) & _MASK
            z = v[p]
        y = v[0]
        v[n] = (v[n] + _round(z, y, total, k[(n & 3) ^ e])) & _MASK
        z = v[n]
        q -= 1
    return _unpack(v, False)


def srun_b64(data: bytes) -> str:
    """按深澜的字母表做 base64。"""
    return base64.b64encode(data).decode().translate(_XLATE)


def hmac_md5_hex(message: str, key: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.md5).hexdigest()


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()
