"""给 `watch --log` 用的文件日志：按大小轮转，别让它涨成几十兆。

只实现 `print` 需要的那点接口（`write` / `flush` / `isatty`），够塞进 `sys.stdout`。
轮转策略故意简单：超限就换名成 `.1`，只留一份备份。两个进程写同一份日志是允许的 ——
轮转失败就当没轮转，本轮文本照旧进去，不允许把 `watch` 带崩。
"""

from __future__ import annotations

import contextlib
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
        """尽力轮转：另一个进程正开着同名文件时 `replace` 会失败，别让它打死调用方。"""
        handle, self._handle = self._handle, None
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()
        for index in range(self.backups, 0, -1):
            older = self.path.with_name(f"{self.path.name}.{index}")
            if index == 1:
                newer = self.path
            else:
                newer = self.path.with_name(f"{self.path.name}.{index - 1}")
            if newer.exists():
                with contextlib.suppress(OSError):
                    newer.replace(older)
        with contextlib.suppress(OSError):
            self._open()

    def write(self, text: str) -> None:
        """写一行。打不开/写不进都不抛 —— 观测设施不该打死主循环。"""
        if not text:
            return
        if self._handle is None:
            try:
                self._open()
            except OSError:
                return
        try:
            self._handle.write(text)
            self._handle.flush()
        except OSError:
            # 句柄失效（被轮转顶掉、文件被删）：留给下一次重开
            self._handle = None
            return
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
    """把一路输出同时写到多个流。

    关心两件事：`None` 流（pythonw 下 `sys.stdout is None`）直接丢掉，以及同一个
    流被传两次时只写一遍（`Tee(log, log)` 不该出双份）。
    """

    def __init__(self, *streams: TextIO | None) -> None:
        unique: list[TextIO] = []
        for stream in streams:
            if stream is not None and all(stream is not seen for seen in unique):
                unique.append(stream)
        self.streams: tuple[TextIO, ...] = tuple(unique)

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
