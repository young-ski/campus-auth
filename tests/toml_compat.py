"""3.10 上测试也得能读 TOML：优先标准库，没有就用仓里那份。"""

from __future__ import annotations

try:  # 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 上走这条
    from campus_auth._vendor import tomli as tomllib  # type: ignore[no-redef]

__all__ = ["tomllib"]
