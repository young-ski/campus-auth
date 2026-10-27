"""配置加载与合并。

优先级（后者覆盖前者）: 内置默认值 < 配置文件 < 环境变量 < 命令行参数。

配置文件位置依次尝试:

    --config PATH
    $CAMPUS_AUTH_CONFIG
    ./campus-auth.toml
    %APPDATA%/campus-auth/config.toml   (Windows)
    ~/.config/campus-auth/config.toml

密码建议只放环境变量 `CAMPUS_AUTH_PASSWORD` 或系统钥匙串，配置文件里留空。
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import credentials
from .errors import ConfigError

ENV_PASSWORD = "CAMPUS_AUTH_PASSWORD"
ENV_CONFIG = "CAMPUS_AUTH_CONFIG"


def _default_config_paths() -> list[Path]:
    paths = [Path.cwd() / "campus-auth.toml"]
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            paths.append(Path(base) / "campus-auth" / "config.toml")
    else:
        paths.append(Path.home() / ".config" / "campus-auth" / "config.toml")
    return paths


@dataclass
class Config:
    adapter: str = "huuc"
    account: str = ""
    password: str = field(default="", repr=False)
    operator: str = "none"
    mac: str = ""
    ip: str = ""
    base_url: str = ""
    verify_tls: bool = False
    timeout: float = 20.0
    retries: int = 2
    interval: float = 120.0
    jitter: float = 0.3
    probe_host: str = "www.baidu.com"
    mask_urls: bool = True

    def validate(self, need_password: bool = True) -> None:
        missing = []
        if not self.adapter:
            missing.append("adapter")
        if not self.account:
            missing.append("account")
        if need_password and not self.password:
            missing.append("password")
        if missing:
            raise ConfigError(
                "缺少必填项: "
                + ", ".join(missing)
                + f"。可运行 `campus-auth init` 生成配置模板，或设 ${ENV_PASSWORD}。"
            )
        if self.password and not self.password.isascii():
            raise ConfigError(
                "密码里有非 ASCII 字符：门户前端只按 ASCII 取 charCode，"
                "发出去的密文会和浏览器不一致。先把密码改成纯 ASCII。"
            )
        if self.operator and self.operator != "none":
            from .adapters import get_adapter

            if self.operator not in get_adapter(self.adapter).operator_suffixes:
                allowed = ", ".join(["none", *get_adapter(self.adapter).operator_suffixes])
                raise ConfigError(
                    f"适配层 {self.adapter} 不认识运营商 {self.operator!r}，可选: {allowed}"
                )


def find_config_file(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"配置文件不存在: {path}")
        return path

    env = os.environ.get(ENV_CONFIG)
    if env:
        path = Path(env)
        if not path.is_file():
            raise ConfigError(f"${ENV_CONFIG} 指向的配置文件不存在: {path}")
        return path

    for path in _default_config_paths():
        if path.is_file():
            return path
    return None


_STRING_FIELDS = {
    "adapter",
    "account",
    "password",
    "operator",
    "mac",
    "ip",
    "base_url",
    "probe_host",
}


def _coerce(name: str, value: Any) -> Any:
    # `account = 81456789` 这类不加引号的写法很常见，下游 ord(ch) 直接吃不下
    if name in _STRING_FIELDS:
        return value if isinstance(value, str) else str(value)
    if name in {"timeout", "interval", "jitter"}:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{name} 必须是数字，得到 {value!r}") from exc
    if name == "retries":
        try:
            return max(0, int(value))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"retries 必须是整数，得到 {value!r}") from exc
    if name == "verify_tls":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    return value


_ALIASES = {
    "school": "adapter",
    "user": "account",
    "pass": "password",
    "weak": "operator",
    "url": "base_url",
}


def load_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 TOML（{path}）: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"读不了配置文件 {path}: {exc}") from exc

    section = raw.get("auth", raw)
    known = {f.name for f in fields(Config)}
    values: dict[str, Any] = {}
    for key, value in section.items():
        name = _ALIASES.get(key, key)
        if name not in known:
            continue
        values[name] = _coerce(name, value)
    return values


def load(
    config_path: str | os.PathLike[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    """组装最终配置。`overrides` 里值为 None 的项会被忽略。"""
    config = Config()

    path = find_config_file(config_path)
    if path is not None:
        for key, value in load_file(path).items():
            setattr(config, key, value)

    overrides = overrides or {}
    for key, value in overrides.items():
        if value is None:
            continue
        if not hasattr(config, key):
            raise ConfigError(f"未知配置项: {key}")
        setattr(config, key, _coerce(key, value))

    # 优先级：命令行 > 环境变量 > 配置文件 > 钥匙串。
    # 钥匙串必须最后查 —— 它的键里带账号，而账号可能刚被命令行改过。
    if "password" in overrides:
        pass
    elif os.environ.get(ENV_PASSWORD):
        config.password = os.environ[ENV_PASSWORD]
    elif not config.password:
        config.password = credentials.get(config.adapter, config.account)

    return config
