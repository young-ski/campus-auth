"""出口网卡探测：IP 精确匹配，别把同前缀的别的网卡认成自己的。"""

from __future__ import annotations

import pytest

from campus_auth import net

TWO_NICS = (
    "\r\nEthernet adapter A:\r\n"
    "   IPv4 Address. . . . . . . . . . : 10.138.14.27\r\n"
    "   Physical Address. . . . . . . . : AA-BB-CC-DD-EE-FF\r\n\r\n"
    "Ethernet adapter B:\r\n"
    "   IPv4 Address. . . . . . . . . . : 10.138.14.2\r\n"
    "   Physical Address. . . . . . . . : 11-22-33-44-55-66\r\n"
)


@pytest.fixture(autouse=True)
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.sys, "platform", "win32")


def fake_ipconfig(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(net, "_run", lambda _cmd: text)


def test_exact_ip_wins_over_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    """`10.138.14.2` 是 `10.138.14.27` 的前缀，旧的子串匹配会拿错网卡。"""
    fake_ipconfig(monkeypatch, TWO_NICS)
    assert net.local_mac("10.138.14.2") == "112233445566"
    assert net.local_mac("10.138.14.27") == "AABBCCDDEEFF"


def test_unknown_ip_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ipconfig(monkeypatch, TWO_NICS)
    assert net.local_mac("10.9.9.9") is None


def test_without_ip_takes_the_first_nic(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ipconfig(monkeypatch, TWO_NICS)
    assert net.local_mac(None) == "AABBCCDDEEFF"


def test_ipconfig_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ipconfig(monkeypatch, "")
    assert net.local_mac("10.1.1.1") is None


def test_chinese_colon_is_understood(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ipconfig(monkeypatch, TWO_NICS.replace(" : ", " ： "))
    assert net.local_mac("10.138.14.2") == "112233445566"
