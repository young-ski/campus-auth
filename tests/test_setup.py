"""`setup` 向导：学号与密码都在窗口里问，门户用假 transport。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_transport import patch_send
from toml_compat import tomllib

from campus_auth import cli, net
from campus_auth.commands import setup

IP = "10.138.14.27"


class TtyStdin:
    """pytest 把 stdin 换成不可读对象，这里装一个"是终端"的。"""

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:  # pragma: no cover - 只在 isatty 为假时用
        return ""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "appdata" / "campus-auth" / "config.toml"
    monkeypatch.setattr(setup, "default_config_path", lambda: cfg)
    monkeypatch.setattr(setup.sys, "stdin", TtyStdin())
    monkeypatch.setattr(net, "local_ip", lambda host, port=80, timeout=5: IP)
    monkeypatch.setattr(net, "local_mac", lambda ip=None: "aabbccddeeff")
    monkeypatch.setattr(net, "current_ssid", lambda: "UCLINK")
    monkeypatch.setattr(net, "reachable", lambda *a, **k: True)
    return cfg


def portal(monkeypatch: pytest.MonkeyPatch) -> dict:
    state = {"online": False, "logins": 0}

    def handler(url: str, _data):
        if "online_list" in url:
            rows = [{"online_ip": IP, "user_account": "0814"}] if state["online"] else []
            return (200, f'cb({{"list": {json.dumps(rows)}}})')
        if "portal/login" in url:
            state["logins"] += 1
            state["online"] = True
            return (200, 'cb({"result":1,"ret_code":0,"msg":"认证成功"})')
        return (200, '{"result":1}')

    patch_send(monkeypatch, handler)
    return state


def drive(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    """按顺序喂 input()，返回被问过的提示语。"""
    queue = list(answers)
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return queue.pop(0) if queue else ""

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def config_of(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---------- 学号 ----------


def test_setup_asks_in_the_console_and_writes_the_account(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不再打开记事本、不再等用户保存：窗口里直接问。"""
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw123")
    portal(monkeypatch)
    prompts = drive(monkeypatch, "0814", "n")
    assert cli.main(["setup"]) == 0
    assert config_of(env)["account"] == "0814"
    assert any("学号" in p for p in prompts)


def test_setup_strips_an_accidental_suffix(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 @cmcc 一起抄进来很常见：取前面的数字，不教训人。"""
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, "0814@cmcc", "n")
    assert cli.main(["setup"]) == 0
    assert config_of(env)["account"] == "0814"


def test_setup_reasks_once_when_the_account_is_not_numeric(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, "abc", "0814", "n")
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "只填数字" in out
    assert config_of(env)["account"] == "0814"


def test_setup_gives_up_after_three_bad_accounts(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    drive(monkeypatch, "abc", "def", "ghi")
    assert cli.main(["setup"]) == 2
    assert "三次" in capsys.readouterr().out
    assert not env.exists()


def test_setup_does_not_mention_the_at_suffix_in_the_prompt(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """提示语里别再教「不要带 @」——那是加分号，不是入门信息。"""
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    cli.main(["setup"])
    out = capsys.readouterr().out
    assert "@ 后缀" not in out
    assert "@cmcc" not in out


# ---------- 密码 ----------


def test_setup_stores_password_in_keyring(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(credentials, "set", lambda a, acc, p: saved.append((a, acc, p)) or True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw123")
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    assert cli.main(["setup"]) == 0
    assert saved == [("huuc", "0814", "pw123")]
    assert config_of(env)["password"] == ""


def test_setup_falls_back_to_config_when_keyring_is_missing(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: False)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw123")
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    assert cli.main(["setup"]) == 0
    config = config_of(env)
    assert config["password"] == "pw123"
    assert config["account"] == "0814"


def test_setup_escapes_the_password_for_toml(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: False)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: 'a"b\\c')
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    assert cli.main(["setup"]) == 0
    assert config_of(env)["password"] == 'a"b\\c'


def test_setup_warns_about_non_ascii_password(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "密码")
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    cli.main(["setup"])
    assert "非 ASCII" in capsys.readouterr().out


# ---------- 验证与自启 ----------


def test_setup_logs_in_and_confirms(env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    state = portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    assert cli.main(["setup"]) == 0
    assert state["logins"] == 1
    assert "登录成功" in capsys.readouterr().out


def test_setup_skips_login_when_already_online(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    state = portal(monkeypatch)
    state["online"] = True
    drive(monkeypatch, "0814", "n")
    assert cli.main(["setup"]) == 0
    assert state["logins"] == 0
    assert "已经在线" in capsys.readouterr().out


def test_setup_autostart_uses_the_pyz_when_running_from_one(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """从压缩包跑时 `python -m campus_auth` 根本不存在，自启必须指向 pyz 文件。"""
    from campus_auth import credentials

    pyz = tmp_path / "campus-auth.pyz"
    pyz.write_bytes(b"PK")
    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    monkeypatch.setattr(setup, "running_pyz", lambda: pyz)
    portal(monkeypatch)
    seen: list[object] = []
    monkeypatch.setattr(setup, "install", lambda service: seen.append(service))
    monkeypatch.setattr(setup, "check_entry", lambda *a, **k: None)
    drive(monkeypatch, "0814", "y")
    assert cli.main(["setup"]) == 0
    service = seen[0]
    assert "campus_auth" not in service.content.replace("campus-auth", "")
    assert "campus-auth.pyz" in service.content


def test_setup_keeps_going_when_autostart_fails(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials
    from campus_auth.errors import ConfigError

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)

    def boom(_service):
        raise ConfigError("systemctl 不在")

    monkeypatch.setattr(setup, "install", boom)
    monkeypatch.setattr(setup, "check_entry", lambda *a, **k: None)
    drive(monkeypatch, "0814", "y")
    assert cli.main(["setup"]) == 0
    assert "自启没装成" in capsys.readouterr().out


def test_setup_requires_force_to_overwrite(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('adapter = "huuc"\naccount = "0814"\n', encoding="utf-8")
    assert cli.main(["setup"]) == 2
    assert "--force" in capsys.readouterr().out


def test_setup_force_reuses_the_existing_account(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('adapter = "huuc"\naccount = "0814"\npassword = ""\n', encoding="utf-8")
    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, "n")
    assert cli.main(["setup", "--force"]) == 0
    assert "沿用上次" in capsys.readouterr().out
    assert config_of(env)["account"] == "0814"


def test_setup_ends_with_doctor_hint(env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    cli.main(["setup"])
    out = capsys.readouterr().out
    assert "campus-auth doctor" in out
    assert "密码不会出现" in out


def test_setup_config_is_owner_only_on_posix(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import stat

    from campus_auth import credentials

    if os.name == "nt":  # pragma: no cover
        pytest.skip("Windows 没有 POSIX 权限位")
    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, "0814", "n")
    cli.main(["setup"])
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
