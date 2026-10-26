"""HTTP 传输：一个 `send()`，`Portal` 和探针共用同一套。

cookie jar、TLS 放宽、UA、`HTTPError` → (状态码, 文本) 的转换全收在这里；
`Portal` 在其上做重试、打码、JSON 解析，探针只管取样。

测试注入一个假的 `Transport` 就够了，不必再去 patch `Portal.request`。
"""

from __future__ import annotations

import contextlib
import http.cookiejar
import ssl
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .errors import TransportError

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) campus-auth"
MAX_BODY = 200_000


def ssl_context(verify: bool) -> ssl.SSLContext:
    """校园门户清一色自签，默认不校验；`SECLEVEL=0` 是为了还在 TLS 1.0 + SHA1 的老门户。"""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(ssl.SSLError):  # 个别 OpenSSL 构建没有该级别
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    return ctx


@dataclass
class Response:
    status: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def send(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 20.0,
        limit: int = MAX_BODY,
    ) -> Response:
        """发一次请求。4xx/5xx 不抛，网络错误抛 `TransportError`。"""
        ...


class UrllibTransport:
    """标准库实现：带 cookie jar，按 `verify` 决定要不要校验证书。"""

    def __init__(self, *, verify_tls: bool = False) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ssl_context(verify_tls)),
        )

    def send(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 20.0,
        limit: int = MAX_BODY,
    ) -> Response:
        request = urllib.request.Request(
            url, data=data, headers={"User-Agent": USER_AGENT, **dict(headers or {})}
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return Response(
                    response.status,
                    response.read(limit).decode("utf-8", "replace"),
                    dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return Response(
                exc.code, exc.read(limit).decode("utf-8", "replace"), dict(exc.headers.items())
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc


__all__ = [
    "MAX_BODY",
    "Response",
    "Transport",
    "USER_AGENT",
    "UrllibTransport",
    "ssl_context",
]
