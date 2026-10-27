"""系统钥匙串里的密码存取（可选依赖 `keyring`）。

键是 `service="campus-auth"`, `username="<adapter>/<account>"` —— 换学校或换账号不会串。

没装 `keyring`、或者后端不可用（headless Linux 常见）时全部退化成"没有"，
调用方照旧走环境变量/配置文件，不必判断。
"""

from __future__ import annotations

SERVICE = "campus-auth"


def _backend():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


_FAIL_BACKENDS = ("keyring.backends.fail",)


def _backend_name(keyring) -> str:
    backend = keyring.get_keyring()
    return f"{type(backend).__module__}.{type(backend).__name__}"


def available() -> bool:
    """能真正存读吗（装了包且后端可用）。

    `keyring.backends.fail.Keyring` 是个永远抛异常的单例，非 `None` 所以不能只判空。
    """
    keyring = _backend()
    if keyring is None:
        return False
    try:
        name = _backend_name(keyring)
    except Exception:  # 后端初始化五花八门，一律当不可用
        return False
    return name.split(".")[0] != "" and not name.startswith(_FAIL_BACKENDS)


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
    """删掉；本来就没有也算删完，后端报错则返回 False。

    「后端坏了」和「本来就没这一条」必须分开 —— 前者要是报成功，`--forget` 就骗人。
    """
    keyring = _backend()
    if keyring is None or not adapter or not account:
        return False
    try:
        keyring.delete_password(SERVICE, _user(adapter, account))
    except Exception as exc:
        problem = type(exc).__name__.lower()
        return problem in {"keyerror", "passworddeleteerror"} or "not found" in str(exc).lower()
    return True


__all__ = ["SERVICE", "available", "delete", "get", "set"]
