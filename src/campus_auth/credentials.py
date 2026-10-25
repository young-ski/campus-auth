"""系统钥匙串里的密码存取（可选依赖 `keyring`）。

键是 `service="campus-auth"`, `username="<adapter>/<account>"` —— 换学校或换账号不会串。

没装 `keyring`、或者后端不可用（headless Linux 常见）时全部退化成"没有"，
调用方照旧走环境变量/配置文件，不必判断。
"""

from __future__ import annotations

import contextlib

SERVICE = "campus-auth"


def _backend():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def available() -> bool:
    """能真正存读吗（装了包且后端可用）。"""
    keyring = _backend()
    if keyring is None:
        return False
    try:
        return keyring.get_keyring() is not None
    except Exception:  # 后端初始化五花八门，一律当不可用
        return False


def _user(adapter: str, account: str) -> str:
    return f"{adapter}/{account}"


def get(adapter: str, account: str) -> str:
    keyring = _backend()
    if keyring is None or not adapter or not account:
        return ""
    try:
        return keyring.get_password(SERVICE, _user(adapter, account)) or ""
    except Exception:
        return ""


def set(adapter: str, account: str, password: str) -> bool:
    """存进去；成功返回 True。"""
    keyring = _backend()
    if keyring is None or not adapter or not account or not password:
        return False
    try:
        keyring.set_password(SERVICE, _user(adapter, account), password)
        return True
    except Exception:
        return False


def delete(adapter: str, account: str) -> bool:
    """删掉；本来就没有也算删完。拿不到后端才返回 False。"""
    keyring = _backend()
    if keyring is None or not adapter or not account:
        return False
    with contextlib.suppress(Exception):  # 没这条就是 PasswordDeleteError，无所谓
        keyring.delete_password(SERVICE, _user(adapter, account))
    return True


__all__ = ["SERVICE", "available", "delete", "get", "set"]
