from __future__ import annotations

import io
from pathlib import Path

import pytest

from campus_auth.logfile import RotatingLog, Tee


def test_writes_and_flushes(tmp_path: Path) -> None:
    log = RotatingLog(tmp_path / "a.log")
    log.write("hello\n")
    assert (tmp_path / "a.log").read_text(encoding="utf-8") == "hello\n"
    log.close()


def test_rotates_at_limit(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    log = RotatingLog(path, limit=1024)
    log.write("x" * 1024)
    log.write("y\n")
    log.close()
    assert (tmp_path / "a.log.1").is_file()
    assert (tmp_path / "a.log").read_text(encoding="utf-8") == "y\n"


def test_keeps_only_configured_backups(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    log = RotatingLog(path, limit=1024, backups=1)
    for index in range(3):
        log.write(f"round{index}" + "x" * 1024)
    log.close()
    assert (tmp_path / "a.log.1").is_file()
    assert not (tmp_path / "a.log.2").exists()


def test_empty_write_is_noop(tmp_path: Path) -> None:
    log = RotatingLog(tmp_path / "a.log")
    log.write("")
    assert not (tmp_path / "a.log").exists()
    log.close()


def test_creates_parent_dir(tmp_path: Path) -> None:
    log = RotatingLog(tmp_path / "deep" / "a.log")
    log.write("x")
    assert (tmp_path / "deep" / "a.log").is_file()
    log.close()


def test_isatty_is_false(tmp_path: Path) -> None:
    assert RotatingLog(tmp_path / "a.log").isatty() is False


def test_tee_writes_everywhere() -> None:
    first, second = io.StringIO(), io.StringIO()
    tee = Tee(first, second)
    tee.write("x")
    tee.flush()
    assert first.getvalue() == second.getvalue() == "x"


def test_tee_drops_none_streams() -> None:
    """pythonw 下 `sys.stdout` 是 None，不许把主循环写崩。"""
    sink = io.StringIO()
    tee = Tee(None, sink)
    tee.write("x")
    tee.flush()
    assert sink.getvalue() == "x"


def test_tee_with_only_none_is_noop() -> None:
    tee = Tee(None, None)
    tee.write("x")
    tee.flush()
    assert tee.isatty() is False


def test_tee_dedupes_the_same_stream() -> None:
    sink = io.StringIO()
    Tee(sink, sink).write("x")
    assert sink.getvalue() == "x"


def test_tee_reports_tty_of_first_stream() -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert Tee(Tty(), io.StringIO()).isatty() is True
    assert Tee(io.StringIO()).isatty() is False


def test_tee_reconfigure_forwards() -> None:
    class Target(io.StringIO):
        seen: dict = {}

        def reconfigure(self, **kwargs) -> None:
            self.seen = kwargs

    target = Target()
    Tee(target).reconfigure(encoding="utf-8")
    assert target.seen == {"encoding": "utf-8"}


def test_rotation_failure_does_not_kill_the_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """另一个进程正开着文件时 `replace` 会抛错，日志器不许把主循环带崩。"""
    path = tmp_path / "a.log"
    log = RotatingLog(path, limit=1024)
    log.write("seed\n")

    def locked(self: Path, target: Path) -> Path:
        raise PermissionError("另一个进程正开着")

    monkeypatch.setattr(Path, "replace", locked)
    log.write("x" * 2000)  # 写超限 → 触发轮转 → replace 抛
    log.close()
    assert "x" * 100 in path.read_text(encoding="utf-8")


def test_open_failure_is_retried_on_next_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.log"
    log = RotatingLog(path)
    real_open = Path.open
    calls = {"n": 0}

    def flaky(self: Path, *args, **kwargs):
        if self == path and calls["n"] == 0:
            calls["n"] += 1
            raise PermissionError("被占用")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky)
    log.write("first\n")  # 打不开，静默
    log.write("second\n")  # 重开成功
    log.close()
    assert "second" in path.read_text(encoding="utf-8")
