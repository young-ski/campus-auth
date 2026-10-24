"""本机网络身份探测：出口 IP、网卡 MAC、当前 SSID、连通性。

IP 是加密密钥的来源，所以只接受"到门户的那块网卡上的 IP"。用 UDP
`socket.connect` 取，不发包，路由查表即可，几毫秒。
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from pathlib import Path

from .errors import EnvironmentError_

_IPCONFIG_MAC = re.compile(r"\b([0-9A-F]{2}(?:-[0-9A-F]{2}){5})\b", re.IGNORECASE)
_SSID_LINE = re.compile(r"^\s*SSID\s*:\s*(\S.*?)\s*$", re.MULTILINE)


def local_ip(host: str, port: int = 80, timeout: float = 5.0) -> str:
    """返回通往 `host:port` 的本机地址。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        ip = sock.getsockname()[0]
    except OSError as exc:  # 没路由 / DNS 挂了
        raise EnvironmentError_(f"探测本机 IP 失败（目标 {host}:{port}）: {exc}") from exc
    finally:
        sock.close()
    if not ip or ip.startswith("127."):
        raise EnvironmentError_(f"本机 IP 是 {ip!r}，像是没连上校园网")
    return ip


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for enc in ("gbk", "utf-8", "latin-1"):
        try:
            return out.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def local_mac(ip: str | None = None) -> str | None:
    """尽量返回出口网卡的 MAC（大写、无分隔）；取不到返回 None。

    `wlan_user_mac` 填全 0 服务端也接受，所以这里失败不算致命。
    """
    if sys.platform == "win32":
        text = _run(["ipconfig", "/all"])
        for block in re.split(r"\r?\n\s*\r?\n", text):
            if ip and ip not in block:
                continue
            match = _IPCONFIG_MAC.search(block)
            if match:
                return match.group(1).replace("-", "").upper()
        return None

    if ip:
        # Linux：用 ip neigh / ip route 拿出口网卡名再读 sysfs
        text = _run(["ip", "route", "get", ip])
        match = re.search(r"\bdev\s+(\S+)", text)
        if match:
            node = Path("/sys/class/net") / match.group(1) / "address"
            try:
                return node.read_text(encoding="ascii").strip().replace(":", "").upper()
            except OSError:
                return None
    return None


def current_ssid() -> str | None:
    """当前 Wi-Fi 的 SSID；有线连接或读不到时返回 None。"""
    if sys.platform == "win32":
        match = _SSID_LINE.search(_run(["netsh", "wlan", "show", "interfaces"]))
        return match.group(1) if match else None
    for cmd in (["iwgetid", "-r"], ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]):
        text = _run(cmd).strip()
        if not text:
            continue
        if cmd[0] == "nmcli":
            for line in text.splitlines():
                if line.startswith("yes:"):
                    return line[4:]
        else:
            return text.splitlines()[0]
    return None


def reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP 探活，用于"断网没断网"的判定。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolves(host: str) -> bool:
    """DNS 能不能解析 —— 门户认证前它一定失败，比 ping 更能说明问题。"""
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False
