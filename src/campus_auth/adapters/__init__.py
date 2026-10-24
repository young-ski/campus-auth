"""适配层注册表。

内置适配层在这里登记；也可以用 `--adapter module:attribute` 从任意
Python 文件加载（写学校适配层时不必改本文件，方便 PR 之外的自用）。
"""

from __future__ import annotations

import importlib
from typing import Final

from ..errors import ConfigError
from .base import Adapter, LoginResult, Param

BUILTIN: Final[dict[str, str]] = {
    "huuc": "campus_auth.adapters.huuc:ADAPTER",
    "generic": "campus_auth.adapters.example_generic:ADAPTER",
}

_cache: dict[str, Adapter] = {}


def _load_target(target: str) -> Adapter:
    module_name, _, attr = target.partition(":")
    attr = attr or "ADAPTER"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigError(f"导出适配层失败（{target}）: {exc}") from exc
    try:
        adapter = getattr(module, attr)
    except AttributeError as exc:
        raise ConfigError(f"{module_name} 里没有 {attr!r}") from exc
    if not isinstance(adapter, Adapter):
        raise ConfigError(f"{target} 是 {type(adapter).__name__}，不是 Adapter 实例")
    adapter.check()
    return adapter


def get_adapter(name: str) -> Adapter:
    """按名字取适配层，`a:b` 形式走动态加载。"""
    if not name:
        raise ConfigError("没有指定适配层（adapter），跑 `campus-auth init` 会生成模板")
    if name in _cache:
        return _cache[name]
    target = name if ":" in name else BUILTIN.get(name, "")
    if not target:
        raise ConfigError(f"没有适配层 {name!r}，内置的有: {', '.join(BUILTIN)}")
    adapter = _load_target(target)
    _cache[name] = adapter
    return adapter


def names() -> list[str]:
    return sorted(BUILTIN)


__all__ = ["Adapter", "LoginResult", "Param", "BUILTIN", "get_adapter", "names"]
