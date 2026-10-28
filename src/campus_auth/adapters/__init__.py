"""适配层注册表。

内置适配层在这里登记；也可以用 `--adapter module:attribute` 从任意模块 **或 .py 文件**
加载（写学校适配层时不必改本文件，PR 之外自用也够）。

文件路径按 `路径.py:ADAPTER` 写；`module:attr` 里的模块名按普通 import 解析。

第三方包也能用：把 `<名字> = 模块:属性` 注册到 `campus_auth.adapters` 这个 entry point 组，
装完就能用 `--adapter <名字>` 选到。同名时内置优先，免得装了包把 huuc 顶掉。
entry point 意味着执行已安装的代码 —— 与 `pip install` 一样的信任前提。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Final

from ..errors import ConfigError
from .base import Adapter, LoginResult, Param

BUILTIN: Final[dict[str, str]] = {
    "huuc": "campus_auth.adapters.huuc:ADAPTER",
    "generic": "campus_auth.adapters.example_generic:ADAPTER",
}

# 外部文件的模块名要唯一，否则同名文件会互相顶掉 sys.modules 里的条目
FILE_PREFIX = "campus_auth_external_"

# 第三方适配层包的 entry point 组
GROUP = "campus_auth.adapters"

_cache: dict[str, Adapter] = {}
_external: dict[str, str] | None = None


def _import_module(module_path: str) -> object:
    """`package.module` 走 import；`目录/x.py` 走文件加载。"""
    path = Path(module_path)
    if path.suffix == ".py" or path.is_file():
        if not path.is_file():
            raise ConfigError(f"适配层文件不存在: {path}")
        name = f"{FILE_PREFIX}{abs(hash(path.resolve()))}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ConfigError(f"加载不了适配层文件: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # 语法错、顶层异常都算「导出不出去」
            raise ConfigError(f"适配层文件跑不起来（{path}）: {exc}") from exc
        return module
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        raise ConfigError(f"导出适配层失败（{module_path}）: {exc}") from exc


def _entry_points() -> dict[str, str]:
    """已安装包声明的适配层：名字 -> `模块:属性`。扫不出来就当没有。"""
    global _external
    if _external is not None:
        return _external
    _external = {}
    try:
        from importlib import metadata

        points = metadata.entry_points(group=GROUP)
    except Exception:  # 老版本 API、坏掉的安装元数据
        return _external
    for point in points:
        _external.setdefault(point.name, point.value)
    return _external


def _load_target(target: str) -> Adapter:
    # 从右切：Windows 盘符 / 绝对路径里也有冒号
    module_path, _, attr = target.rpartition(":")
    if not module_path:
        module_path, attr = target, ""
    attr = attr or "ADAPTER"
    module = _import_module(module_path)
    try:
        adapter = getattr(module, attr)
    except AttributeError as exc:
        raise ConfigError(f"{module_path} 里没有 {attr!r}") from exc
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
    if not target and ":" not in name:
        target = _entry_points().get(name, "")
    if not target:
        raise ConfigError(
            f"没有适配层 {name!r}，内置的有: {', '.join(BUILTIN)}；第三方适配层看 docs/schools.md"
        )
    adapter = _load_target(target)
    _cache[name] = adapter
    return adapter


def names() -> list[str]:
    return sorted({*BUILTIN, *_entry_points()})


__all__ = ["Adapter", "LoginResult", "Param", "BUILTIN", "get_adapter", "names"]
