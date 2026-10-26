"""把配置变成可用的 `Portal`：解析身份、挑适配层、拼平台提示。"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from . import net
from .adapters import Adapter, get_adapter
from .config import Config
from .errors import ConfigError, EnvironmentError_
from .portal import Portal


@dataclass
class Context:
    config: Config
    adapter: Adapter
    portal: Portal
    ip: str
    mac: str
    ssid: str | None
    zone: str
    zone_hint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "adapter": self.adapter.name,
            "school": self.adapter.school,
            "account": self.config.account,
            "operator": self.config.operator,
            "ip": self.ip,
            "mac": self.mac,
            "ssid": self.ssid,
            "zone": self.zone,
            "zone_hint": self.zone_hint,
            "portal": self.portal.base_url,
        }


def _host_port(base_url: str) -> tuple[str, int]:
    parts = urllib.parse.urlsplit(base_url)
    if not parts.hostname:
        raise ConfigError(f"base_url 里没有主机名: {base_url!r}")
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def build(config: Config, *, need_password: bool = True) -> Context:
    config.validate(need_password=need_password)
    adapter = get_adapter(config.adapter)

    base_url = config.base_url or adapter.base_url
    host, port = _host_port(base_url)

    ip = config.ip or net.local_ip(host, port)
    mac = (config.mac or net.local_mac(ip) or "").upper().replace(":", "").replace("-", "")
    if mac and len(mac) != 12:
        raise ConfigError(f"MAC 看起来不对: {config.mac!r}，应为 12 位十六进制")
    ssid = net.current_ssid()

    zone, _, _, _ = _zone_of(adapter, ip, ssid)
    portal = Portal(
        adapter,
        base_url=base_url,
        verify_tls=config.verify_tls,
        timeout=config.timeout,
        retries=config.retries,
        ip=ip,
        mac=mac or "0" * 12,
        account=config.account,
        password=config.password,
        operator=config.operator,
    )
    return Context(
        config=config,
        adapter=adapter,
        portal=portal,
        ip=ip,
        mac=mac,
        ssid=ssid,
        zone=zone,
        zone_hint=adapter.zone_hint(ip, ssid),
    )


def _zone_of(
    adapter: Adapter, ip: str, ssid: str | None
) -> tuple[str, str | None, str | None, str]:
    zone_of = getattr(adapter, "zone_of", None)
    if callable(zone_of):
        return zone_of(ip, ssid)
    return ("未知", ssid, None, "none")


def require_campus(ctx: Context) -> None:
    """连门户都探不到时提前报错，别浪费时间重试。"""
    host, port = _host_port(ctx.portal.base_url)
    if not net.reachable(host, port, timeout=4):
        raise EnvironmentError_(
            f"连不上门户 {host}:{port} —— 多半不在校园网内，或 portal 地址写错了。"
        )
