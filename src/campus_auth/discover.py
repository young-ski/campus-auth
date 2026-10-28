"""在校园网里没有地址也能开工：从劫持页把门户地址捞出来。

认证前的门户会拦下任意 HTTP 请求并回一个跳转页/302，所以「先探测」不必
让人先知道门户 IP。已经在线时没有可捞的东西，这时要退回让用户给 `--url`。
"""

from __future__ import annotations

import urllib.parse

from .errors import ConfigError, TransportError
from .probe import _CAPTIVE
from .transport import MAX_BODY, Transport

# 两个公开探针地址，任何一个被劫持都能拿到跳转目标
CANARIES = (
    "http://connect.rom.miui.com/generate_204",
    "http://www.baidu.com",
)

TIMEOUT = 5.0


def _portal_from(response_url: str, location: str, canary: str) -> str | None:
    """挑出「跟探针不同主机」的那个地址；同主机说明没被劫持。"""
    canary_host = urllib.parse.urlsplit(canary).hostname or ""
    for candidate in (location, response_url):
        if not candidate:
            continue
        parts = urllib.parse.urlsplit(candidate)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            continue
        if parts.hostname == canary_host:
            continue
        return candidate
    return None


def discover_portal(transport: Transport, *, timeout: float = TIMEOUT) -> str:
    """返回劫持页指向的门户地址。

    已经在线、或探针一条都不通时抛 `ConfigError` —— 这种情况没有可捞的地址，
    得让用户显式给 `--url`。
    """
    for canary in CANARIES:
        try:
            response = transport.send(
                canary, timeout=timeout, limit=MAX_BODY, allow_redirects=False
            )
        except TransportError:
            continue
        location = response.headers.get("location") or response.headers.get("Location") or ""
        found = _portal_from(response.url, location, canary)
        if found:
            return found
        match = _CAPTIVE.search(response.text)
        if match:
            found = _portal_from("", match.group(1), canary)
            if found:
                return found
        if response.status in {200, 204} and not location:
            # 没被劫持：要么已认证，要么这地址本来就不该劫持
            continue
    raise ConfigError(
        "没从劫持页找到门户地址（可能已经在线，或不在校园网内）："
        "用 `campus-auth probe --url http://<门户IP>` 显式指定。"
    )
