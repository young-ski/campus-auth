"""跨进程留一点小状态（目前只存锐捷的 `userIndex`）。

锐捷注销要登录时拿到的 `userIndex`，可 `login` 和 `logout` 本就是两条命令、两个进程。
这里把它落到配置目录的 `state.json`，带 TTL —— 掉线太久就不必再拿旧值去撞。

存的东西不是凭据（不含密码），可以随便看。路径用 `$CAMPUS_AUTH_STATE` 换掉，
换到不敢写的地方也只是这层空转，不影响登录。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ENV_STATE = "CAMPUS_AUTH_STATE"
TTL = 12 * 3600.0
_MAX_RECORDS = 32


def state_path() -> Path:
    explicit = os.environ.get(ENV_STATE)
    if explicit:
        return Path(explicit)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) / "campus-auth" if base else Path.home() / ".campus-auth"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        root = Path(config_home) / "campus-auth"
    return root / "state.json"


def _same(record: dict, adapter: str, account: str, ip: str) -> bool:
    return (
        record.get("adapter") == adapter
        and record.get("account") == account
        and record.get("ip") == ip
    )


def _alive(record: dict, now: float) -> bool:
    try:
        return now - float(record["ts"]) < TTL
    except (KeyError, TypeError, ValueError):
        return False


def _read() -> list[dict]:
    """读失败一律当空：状态文件坏了不该挡住登录。"""
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    records = raw.get("records") if isinstance(raw, dict) else None
    return [row for row in records if isinstance(row, dict)] if isinstance(records, list) else []


def _write(records: list[dict]) -> None:
    path = state_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)
        if os.name == "posix":
            path.chmod(0o600)
    except OSError:
        pass


def save_user_index(adapter: str, account: str, ip: str, index: str) -> None:
    if not index:
        return
    now = time.time()
    records = [row for row in _read() if _alive(row, now) and not _same(row, adapter, account, ip)]
    records.append(
        {"adapter": adapter, "account": account, "ip": ip, "userIndex": index, "ts": now}
    )
    _write(records[-_MAX_RECORDS:])


def load_user_index(adapter: str, account: str, ip: str) -> str:
    now = time.time()
    for record in reversed(_read()):
        if _same(record, adapter, account, ip) and _alive(record, now):
            return str(record.get("userIndex") or "")
    return ""


def drop_user_index(adapter: str, account: str, ip: str) -> None:
    _write([row for row in _read() if not _same(row, adapter, account, ip)])


__all__ = [
    "ENV_STATE",
    "TTL",
    "drop_user_index",
    "load_user_index",
    "save_user_index",
    "state_path",
]
