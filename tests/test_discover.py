"""没有 `--url` 时从劫持页捞门户地址。"""

from __future__ import annotations

import pytest

from campus_auth.discover import CANARIES, discover_portal
from campus_auth.errors import ConfigError, TransportError
from campus_auth.transport import Response

PORTAL = "http://10.210.213.208:802"


class StubTransport:
    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, bool]] = []

    def send(self, url: str, *, allow_redirects: bool = True, **_kwargs) -> Response:
        self.calls.append((url, allow_redirects))
        reply = self.replies.pop(0) if self.replies else Response(204, "")
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_redirect_location_is_used() -> None:
    transport = StubTransport(Response(302, "", {"location": PORTAL}))
    assert discover_portal(transport) == PORTAL
    # 不许跟随：跟下去就拿不到门户地址了
    assert transport.calls == [(CANARIES[0], False)]


def test_script_redirect_is_used() -> None:
    body = f"<script>location.href='{PORTAL}/eportal/index.jsp'</script>"
    transport = StubTransport(Response(200, body))
    assert discover_portal(transport).startswith(PORTAL)


def test_second_canary_is_tried_after_a_failure() -> None:
    transport = StubTransport(TransportError("超时"), Response(302, "", {"location": PORTAL}))
    assert discover_portal(transport) == PORTAL
    assert [url for url, _ in transport.calls] == list(CANARIES)


def test_same_host_redirect_is_not_the_portal() -> None:
    """有些网络把 generate_204 转到自己的 CDN，那不算门户。"""
    transport = StubTransport(
        Response(302, "", {"location": "http://connect.rom.miui.com/elsewhere"}),
        Response(204, ""),
    )
    with pytest.raises(ConfigError, match="--url"):
        discover_portal(transport)


def test_online_network_has_nothing_to_discover() -> None:
    transport = StubTransport(Response(204, ""), Response(204, ""))
    with pytest.raises(ConfigError, match="已经在线"):
        discover_portal(transport)


def test_response_url_is_used_when_location_is_missing() -> None:
    transport = StubTransport(Response(200, "<html>登录</html>"))
    transport.replies[0].url = PORTAL  # 跟随后拿到的最终地址
    assert discover_portal(transport) == PORTAL
