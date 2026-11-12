from __future__ import annotations

from pathlib import Path

import pytest

from campus_auth import install
from campus_auth.errors import ConfigError


@pytest.fixture(autouse=True)
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把两处目录都挪进 tmp，别写真实的 APPDATA / XDG。"""
    monkeypatch.setenv("APPDATA", str(tmp_path / "app"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path


def test_systemd_unit_shape(tmp_path: Path) -> None:
    config = tmp_path / "my config.toml"
    service = install.service_for(config, python="/usr/bin/python3", platform="linux")
    assert service.kind == "systemd"
    assert service.path.name == "campus-auth-watch.service"
    # systemd 只扫 $XDG_CONFIG_HOME/systemd/user，多套一层 campus-auth/ 就找不到
    assert service.path == tmp_path / "cfg" / "systemd" / "user" / "campus-auth-watch.service"
    # 带空格要引号、`%` 要写成 `%%`、引号内反斜杠要转义
    exec_line = next(x for x in service.content.splitlines() if x.startswith("ExecStart"))
    assert exec_line.startswith("ExecStart=/usr/bin/python3 -u -m campus_auth watch --config ")
    assert install._unit_line([str(config)]) in exec_line
    assert '"' in exec_line
    assert "Restart=always" in service.content
    assert service.log_path.as_posix().endswith("state/campus-auth/watch.log")
    assert service.remove[0] == ["systemctl", "--user", "disable", "--now", service.path.name]


def test_launchd_plist_shape(tmp_path: Path) -> None:
    service = install.service_for(tmp_path / "c.toml", python="/usr/bin/python3", platform="darwin")
    assert service.kind == "launchd"
    assert service.path.name == "cn.campus-auth.watch.plist"
    assert "<string>cn.campus-auth.watch</string>" in service.content
    assert "<key>KeepAlive</key><true/>" in service.content
    assert service.remove == [["launchctl", "unload", "-w", str(service.path)]]


def test_windows_uses_run_key(tmp_path: Path) -> None:
    service = install.service_for(
        tmp_path / "c.toml", python=str(tmp_path / "python.exe"), platform="win32"
    )
    assert service.kind == "run-key"
    assert service.path.suffix == ".cmd"
    assert "@echo off" in service.content
    # 崩了要能自己重起：Run 键只在登录时拉一次，没有守护进程
    assert ":loop" in service.content
    assert "goto loop" in service.content
    assert "--log" in service.content
    assert service.create[0][:3] == ["reg", "add", install.RUN_KEY]
    assert service.remove == [["reg", "delete", install.RUN_KEY, "/v", install.TASK_NAME, "/f"]]


def test_windows_prefers_pythonw(tmp_path: Path) -> None:
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    service = install.service_for(
        tmp_path / "c.toml", python=str(tmp_path / "python.exe"), platform="win32"
    )
    assert "pythonw.exe" in service.content


def test_systemd_and_launchd_have_commands(tmp_path: Path) -> None:
    linux = install.service_for(tmp_path / "c.toml", platform="linux")
    macos = install.service_for(tmp_path / "c.toml", platform="darwin")
    assert linux.create and linux.remove
    assert macos.create and macos.remove


def test_unknown_platform_refuses(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="自己配一个"):
        install.service_for(tmp_path / "c.toml", platform="plan9")


def test_install_writes_file_and_runs_commands(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    service = install.service_for(tmp_path / "c.toml", platform="linux")
    install.install(service, run=calls.append)
    assert service.path.is_file()
    assert calls == service.create
    assert service.log_path.parent.is_dir()


def test_install_dry_run_touches_nothing(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    service = install.service_for(tmp_path / "c.toml", platform="linux")
    install.install(service, dry_run=True, run=calls.append)
    assert calls == []
    assert not service.path.exists()


def test_uninstall_stops_then_removes(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    service = install.service_for(tmp_path / "c.toml", platform="linux")
    install.install(service, run=lambda _argv: None)
    install.uninstall(service, run=calls.append)
    assert calls == service.remove
    assert not service.path.exists()


def test_uninstall_without_file_is_ok(tmp_path: Path) -> None:
    service = install.service_for(tmp_path / "c.toml", platform="linux")
    install.uninstall(service, run=lambda _argv: None)  # 不该抛


def test_check_python_ok(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    install.check_python(str(tmp_path / "python.exe"), run=calls.append)
    assert calls == [[str(tmp_path / "python.exe"), "-c", "import campus_auth"]]


def test_check_python_failure_is_actionable(tmp_path: Path) -> None:
    def fail(_argv: list[str]) -> None:
        raise ConfigError("找不到命令")

    with pytest.raises(ConfigError, match="import 不到 campus_auth"):
        install.check_python("/usr/bin/python3", run=fail)


HOSTILE = Path("C:/a&b/100% x/c.toml")


def test_windows_quotes_every_arg_and_escapes_percent() -> None:
    service = install.service_for(HOSTILE, python="C:/py thon/python.exe", platform="win32")
    line = next(x for x in service.content.splitlines() if "campus_auth" in x)
    assert line.startswith('"C:/py thon/python.exe"')
    assert "100%% x" in line
    assert f'"{str(HOSTILE).replace("%", "%%")}"' in line


def test_systemd_escapes_percent_and_quotes_spaces() -> None:
    service = install.service_for(HOSTILE, python="/opt/py thon/python3", platform="linux")
    exec_line = next(x for x in service.content.splitlines() if x.startswith("ExecStart"))
    assert "100%% x" in exec_line
    assert '"/opt/py thon/python3"' in exec_line


def test_launchd_plist_is_valid_xml() -> None:
    import xml.etree.ElementTree as ET

    service = install.service_for(HOSTILE, platform="darwin")
    ET.fromstring(service.content)
    assert "a&amp;b" in service.content


def test_pyz_runs_the_file_instead_of_the_module() -> None:
    """从压缩包跑时 `python -m campus_auth` 不存在，自启必须指 pyz。"""
    from pathlib import Path

    from campus_auth.install import service_for

    pyz = Path("C:/x/campus-auth.pyz")
    win = service_for(Path("C:/x/c.toml"), python="python.exe", platform="win32", pyz=pyz)
    assert "campus-auth.pyz" in win.content
    assert "-m" not in win.content


def test_module_mode_is_still_the_default() -> None:
    from pathlib import Path

    from campus_auth.install import service_for

    win = service_for(Path("C:/x/c.toml"), python="python.exe", platform="win32")
    assert "-m" in win.content
    assert "campus_auth" in win.content


def test_adopt_pyz_copies_next_to_the_config(tmp_path, monkeypatch) -> None:
    """删掉解压目录不该让自启失效，所以副本要落到配置目录。"""
    from campus_auth import install as installer

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(installer.sys, "platform", "win32")
    source = tmp_path / "download" / "campus-auth.pyz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PK\x03\x04")

    adopted = installer.adopt_pyz(source, platform="win32")
    assert adopted != source
    assert adopted.read_bytes() == b"PK\x03\x04"
    assert adopted.parent.name == "campus-auth"


def test_adopt_pyz_is_a_noop_when_already_in_place(tmp_path, monkeypatch) -> None:
    from campus_auth import install as installer

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    target = tmp_path / "appdata" / "campus-auth" / "campus-auth.pyz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"PK")
    assert installer.adopt_pyz(target, platform="win32") == target


def test_uninstall_tolerates_an_already_removed_entry(tmp_path) -> None:
    """点两次卸载是常态：已经不在的东西不该让命令失败。"""
    from campus_auth.errors import ConfigError
    from campus_auth.install import Service, uninstall

    def missing(_argv):
        raise ConfigError("ERROR: The system was unable to find the specified registry key")

    service = Service(
        kind="run-key",
        path=tmp_path / "gone.cmd",
        log_path=tmp_path / "w.log",
        content="x",
        remove=[["reg", "delete", "x"]],
    )
    failures = uninstall(service, run=missing)
    assert len(failures) == 1
    assert "unable to find" in failures[0]
