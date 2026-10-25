"""给 `watch --log` 用的文件日志：按大小轮转，别让它涨成几十兆。

只实现 `print` 需要的那点接口（`write` / `flush` / `isatty`），够塞进 `sys.stdout`。
轮转策略故意简单：超限就换名成 `.1`，只留一份备份。
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

DEFAULT_LIMIT = 1 << 20  # 1 MiB，够查一天的故障
DEFAULT_BACKUPS = 1


class RotatingLog:
    def __init__(self, path: Path, *, limit: int = DEFAULT_LIMIT, backups: int = DEFAULT_BACKUPS):
        self.path = path
        self.limit = max(1024, limit)
        self.backups = max(1, backups)
        self._handle: TextIO | None = None
        self._size = 0

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8", errors="replace")
        self._size = self.path.stat().st_size

    def _rotate(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        for index in range(self.backups, 0, -1):
            older = self.path.with_name(f"{self.path.name}.{index}")
            if index == 1:
                newer = self.path
            else:
                newer = self.path.with_name(f"{self.path.name}.{index - 1}")
            if newer.exists():
                newer.replace(older)
        self._open()

    def write(self, text: str) -> None:
        if not text:
            return
        if self._handle is None:
            self._open()
        assert self._handle is not None
        self._handle.write(text)
        self._handle.flush()
        self._size += len(text.encode("utf-8", "replace"))
        if self._size >= self.limit:
            self._rotate()

    def flush(self) -> None:
        if self._handle is not None:
            self._handle.flush()

    def isatty(self) -> bool:
        return False

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


class Tee:
    """把一路输出同时写到多个流。"""

    def __init__(self, *streams: TextIO) -> None:
        self.streams: tuple[TextIO, ...] = streams

    def write(self, text: str) -> None:
        for stream in self.streams:
            stream.write(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()

    def isatty(self) -> bool:
        return bool(self.streams and getattr(self.streams[0], "isatty", lambda: False)())

    def reconfigure(self, **kwargs: object) -> None:
        for stream in self.streams:
            method = getattr(stream, "reconfigure", None)
            if callable(method):
                method(**kwargs)


__all__ = ["DEFAULT_BACKUPS", "DEFAULT_LIMIT", "RotatingLog", "Tee"]
