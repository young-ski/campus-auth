"""`setup` 向导：只测它自己的流程，门户用假 transport。"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fake_transport import patch_send

from campus_auth import cli, net
from campus_auth.commands import setup

IP = "10.138.14.27"


class TtyStdin:
    """pytest 把 stdin 换成不可读对象，这里装一个"是终端"的。"""

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:  # pragma: no cover  - 只在 isatty 为假时用
        return ""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把默认配置路径挪进 tmp，并让门户永远"不在线但可登录"。"""
    cfg = tmp_path / "appdata" / "campus-auth" / "config.toml"
    monkeypatch.setattr(setup, "default_config_path", lambda: cfg)
    monkeypatch.setattr(setup, "_open_in_editor", lambda _path: True)
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


def fill_account(cfg: Path, account: str) -> None:
    """模拟同学在记事本里改完配置。"""
    text = cfg.read_text(encoding="utf-8")
    cfg.write_text(text.replace('account = ""', f'account = "{account}"'), encoding="utf-8")


def drive(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Path,
    *after: str,
    account: str | None = "0814",
) -> None:
    """按回车时顺手把学号填好，之后依次回答 `after`。"""
    pending = list(after)

    def fake_input(prompt: str = "") -> str:
        if account is not None and "回车" in prompt:
            fill_account(cfg, account)
            return ""
        return pending.pop(0) if pending else ""

    monkeypatch.setattr("builtins.input", fake_input)


def test_setup_writes_config_and_needs_force_to_overwrite(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('adapter = "huuc"\n', encoding="utf-8")
    assert cli.main(["setup"]) == 2
    assert "--force" in capsys.readouterr().out


def test_setup_requires_a_filled_account(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    drive(monkeypatch, env, account=None)
    assert cli.main(["setup"]) == 2
    out = capsys.readouterr().out
    assert "还是空的" in out
    # 模板必须已经落盘，别让同学白填一遍
    assert env.is_file()


def test_setup_rejects_non_numeric_account(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    drive(monkeypatch, env, account="0814@cmcc")
    assert cli.main(["setup"]) == 2
    assert "只填数字" in capsys.readouterr().out


def test_setup_names_the_suffix_mistake(env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """`0814@cmcc` 是最常见的手填错误，要当场说清后缀归 -w 管。"""
    drive(monkeypatch, env, account="0814@cmcc")
    assert cli.main(["setup"]) == 2
    assert "别带 @cmcc" in capsys.readouterr().out


def test_setup_stores_password_in_keyring(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(credentials, "set", lambda a, acc, p: saved.append((a, acc, p)) or True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw123")
    portal(monkeypatch)
    drive(monkeypatch, env, "n")
    code = cli.main(["setup"])
    out = capsys.readouterr().out
    assert code == 0, out[-800:]
    assert saved == [("huuc", "0814", "pw123")]
    # 进了钥匙串就不该在配置里留明文
    assert tomllib.loads(env.read_text(encoding="utf-8"))["password"] == ""


def test_setup_falls_back_to_config_when_keyring_is_missing(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: False)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw123")
    portal(monkeypatch)
    drive(monkeypatch, env, "n")
    assert cli.main(["setup"]) == 0
    config = tomllib.loads(env.read_text(encoding="utf-8"))
    assert config["password"] == "pw123"
    assert config["account"] == "0814"


def test_setup_escapes_the_password_for_toml(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: False)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: 'a"b\\c')
    portal(monkeypatch)
    drive(monkeypatch, env, "n")
    assert cli.main(["setup"]) == 0
    assert tomllib.loads(env.read_text(encoding="utf-8"))["password"] == 'a"b\\c'


def test_setup_logs_in_and_confirms(env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    state = portal(monkeypatch)
    drive(monkeypatch, env, "n")
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
    drive(monkeypatch, env, "n")
    assert cli.main(["setup"]) == 0
    assert state["logins"] == 0
    assert "已经在线" in capsys.readouterr().out


def test_setup_installs_autostart_on_yes(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    installed: list[object] = []
    monkeypatch.setattr(setup, "install", lambda service: installed.append(service))
    monkeypatch.setattr(setup, "check_python", lambda _py: None)
    drive(monkeypatch, env, "y")
    assert cli.main(["setup"]) == 0
    assert len(installed) == 1
    assert "已装成登录自启" in capsys.readouterr().out


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
    monkeypatch.setattr(setup, "check_python", lambda _py: None)
    drive(monkeypatch, env, "y")
    assert cli.main(["setup"]) == 0
    assert "自启没装成" in capsys.readouterr().out


def test_setup_warns_about_non_ascii_password(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "密码")
    portal(monkeypatch)
    drive(monkeypatch, env, "n")
    cli.main(["setup"])
    assert "非 ASCII" in capsys.readouterr().out


def test_setup_ends_with_doctor_hint(env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, env, "n")
    cli.main(["setup"])
    out = capsys.readouterr().out
    assert "campus-auth doctor" in out
    assert "密码不会出现" in out


def test_setup_force_reuses_the_existing_account(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """重跑别让人再填一遍学号，也别为了它停在那里等回车。"""
    from campus_auth import credentials

    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('adapter = "huuc"\naccount = "0814"\npassword = ""\n', encoding="utf-8")
    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _p="": "n")
    assert cli.main(["setup", "--force"]) == 0
    text = capsys.readouterr().out
    assert "沿用原来的学号 0814" in text


def test_setup_config_is_owner_only_on_posix(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import stat

    from campus_auth import credentials

    if os.name == "nt":  # pragma: no cover
        pytest.skip("Windows 没有 POSIX 权限位")
    monkeypatch.setattr(credentials, "set", lambda *a: True)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _p: "pw")
    portal(monkeypatch)
    drive(monkeypatch, env, "n")
    cli.main(["setup"])
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
