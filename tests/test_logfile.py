from __future__ import annotations

import io
from pathlib import Path

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
