from __future__ import annotations

import pytest

from campus_auth.crypto import xor_hex, xor_key, xor_unhex

# 真实抓包得到的向量：密钥只由 IP 字符异或而来
VECTORS = {
    "10.152.59.163": 0x21,  # 教学楼网段
    "10.138.14.27": 0x15,  # 宿舍网段
}


@pytest.mark.parametrize(("ip", "expected"), VECTORS.items())
def test_key_matches_capture(ip: str, expected: int) -> None:
    assert xor_key(ip) == expected


def test_key_of_empty_is_zero() -> None:
    assert xor_key("") == 0


def test_hex_matches_capture() -> None:
    key = xor_key("10.152.59.163")
    assert xor_hex("1", key) == "10"
    assert xor_hex("zh", key) == "5b49"


@pytest.mark.parametrize("ip", ["10.152.59.163", "10.138.14.27", "192.168.1.1"])
@pytest.mark.parametrize(
    "text", ["", "1", "zh", ",0,081456789@cmcc", "4.2.1", "0.1234567890123456"]
)
def test_roundtrip(ip: str, text: str) -> None:
    key = xor_key(ip)
    assert xor_unhex(xor_hex(text, key), key) == text


def test_hex_is_lowercase_two_digits() -> None:
    out = xor_hex("0123456789", 0x21)
    assert len(out) == 20
    assert out == out.lower()


def test_key_depends_on_ip() -> None:
    assert xor_key("10.152.59.163") != xor_key("10.152.59.164")


def test_unhex_rejects_odd_length() -> None:
    with pytest.raises(ValueError):
        xor_unhex("abc", 0x21)
