"""假的 `Transport`：按队列回放响应或异常，并记住每次调用。

测试不必再 patch `Portal.request` / `portal._opener`，把 `FakeTransport` 注入
`Portal(..., transport=...)` 就行。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from campus_auth.transport import Response, UrllibTransport

Reply = tuple[int, str] | tuple[int, str, Mapping[str, str]] | Exception


class FakeTransport:
    def __init__(self, *replies: Reply) -> None:
        self.replies: list[Reply] = list(replies)
        self.calls: list[dict[str, object]] = []

    def send(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 0,
        limit: int = 0,
    ) -> Response:
        self.calls.append({"url": url, "data": data, "headers": dict(headers or {})})
        reply = self.replies.pop(0) if self.replies else (200, "{}")
        if isinstance(reply, Exception):
            raise reply
        status, text = reply[0], reply[1]
        extra = reply[2] if len(reply) == 3 else {}
        return Response(status, text, dict(extra))

    @property
    def last_url(self) -> str:
        return str(self.calls[-1]["url"]) if self.calls else ""


def patch_send(monkeypatch, handler: Callable[[str, bytes | None], object]) -> None:
    """把 `UrllibTransport.send` 换成 handler(url, data)。

    handler 返回 `Response` / `(status, text)` / 异常；在 transport 层打桩，
    `build_url`、编码、重试、解析都还是真的。
    """

    def fake(self, url, *, data=None, headers=None, timeout=0, limit=0):
        result = handler(url, data)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, Response):
            return result
        if isinstance(result, tuple):
            return Response(result[0], result[1], {})
        return Response(200, str(result), {})

    monkeypatch.setattr(UrllibTransport, "send", fake)


class DictTransport:
    """按 URL 查表回 200；查不到抛 `TransportError`（模仿取不到）。"""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def send(self, url: str, *, data=None, headers=None, timeout=0, limit=0) -> Response:
        self.calls.append(url)
        if url not in self.pages:
            from campus_auth.errors import TransportError

            raise TransportError(f"{url} 取不到")
        return Response(200, self.pages[url], {"server": "nginx"})
