from __future__ import annotations

import pytest

from campus_auth.crypto_srun import hmac_md5_hex, sha1_hex, srun_b64, xxtea

# 来自 vidar-team/srun-login 的 internal/crypotoutil/encode_test.go
VECTOR_IN = b"aaaaaaaaaaaa"
VECTOR_KEY = b"bbbbbbbbbbbb"
VECTOR_OUT = bytes.fromhex("d4eb3234a6e57d455fdca5bcbefb3ad1")


def test_xxtea_matches_reference_vector() -> None:
    assert xxtea(VECTOR_IN, VECTOR_KEY) == VECTOR_OUT


def test_xxtea_empty() -> None:
    assert xxtea(b"", b"key") == b""


def test_xxtea_key_dependent() -> None:
    assert xxtea(VECTOR_IN, VECTOR_KEY) != xxtea(VECTOR_IN, b"cccccccccccc")


def test_xxtea_short_key_is_padded() -> None:
    assert xxtea(b"abc", b"k") != b""


def test_srun_b64_alphabet() -> None:
    # 标准表 "/" 在深澜表里是 "A"（第 63 位），"A" 是 "L"（第 0 位）
    assert srun_b64(b"\xff\xff\xff") == "AAAA"
    assert srun_b64(b"\x00\x00\x00") == "LLLL"


def test_srun_b64_matches_reference_encode() -> None:
    assert srun_b64(VECTOR_OUT) == "jybx08WpsHus78a4wwbBt+=="


def test_hmac_md5_uses_key() -> None:
    assert hmac_md5_hex("password", "challenge") != hmac_md5_hex("password", "other")
    assert len(hmac_md5_hex("x", "y")) == 32


def test_sha1_hex() -> None:
    assert sha1_hex("abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 7, 8, 11, 16, 17])
def test_xxtea_handles_ragged_lengths(size: int) -> None:
    assert len(xxtea(b"x" * size, VECTOR_KEY)) > 0
