from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_transport import patch_send

from campus_auth import cli, net
from campus_auth.portal import Portal

IP = "10.138.14.27"


@pytest.fixture
def campus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAMPUS_AUTH_PASSWORD", raising=False)
    # 放在独立文件里，别占用 init 的默认输出路径
    config = tmp_path / "cfg.toml"
    config.write_text('adapter = "huuc"\naccount = "0814"\npassword = "pw"\n', encoding="utf-8")
    monkeypatch.setenv("CAMPUS_AUTH_CONFIG", str(config))
    monkeypatch.setattr(net, "local_ip", lambda host, port=80, timeout=5: IP)
    monkeypatch.setattr(net, "local_mac", lambda ip=None: "aabbccddeeff")
    monkeypatch.setattr(net, "current_ssid", lambda: "UCSIG")
    monkeypatch.setattr(net, "reachable", lambda *a, **k: True)
    monkeypatch.setattr(net, "resolves", lambda host: False)
    return tmp_path


def fake_portal(monkeypatch: pytest.MonkeyPatch, *, online_after_login: bool = True) -> dict:
    """在 transport 层打桩：URL 拼接、编码、解析全走真的。"""
    state = {"online": False, "logins": 0, "calls": []}

    def handler(url: str, _data):
        state["calls"].append(url)
        if "online_list" in url:
            rows = [{"online_ip": IP, "user_account": "0814"}] if state["online"] else []
            return (200, f'cb({{"list": {json.dumps(rows)}}})')
        if "portal/login" in url:
            state["logins"] += 1
            state["online"] = online_after_login
            return (200, 'cb({"result":1,"ret_code":0,"msg":"认证成功"})')
        return (200, '{"result":1,"msg":"ok"}')

    patch_send(monkeypatch, handler)
    return state


def run(argv: list[str]) -> int:
    return cli.main(argv)


# ---------- init ----------


def test_init_writes_template(campus: Path) -> None:
    assert run(["init"]) == 0
    text = (campus / "campus-auth.toml").read_text(encoding="utf-8")
    assert 'adapter = "huuc"' in text
    assert 'operator = "none"' in text
    assert "CAMPUS_AUTH_PASSWORD" in text


def test_init_refuses_overwrite(campus: Path) -> None:
    run(["init"])
    assert run(["init"]) == 2
    assert run(["init", "--force"]) == 0


def test_init_picks_operator_list(campus: Path) -> None:
    run(["init"])
    assert "cmcc" in (campus / "campus-auth.toml").read_text(encoding="utf-8")


# ---------- adapters ----------


def test_adapters_lists_builtins(campus: Path, capsys: pytest.CaptureFixture) -> None:
    assert run(["adapters"]) == 0
    out = capsys.readouterr().out
    assert "huuc" in out and "河南城建学院" in out


# ---------- status / check ----------


def test_status_offline(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_portal(monkeypatch)
    assert run(["status"]) == 1
    out = capsys.readouterr().out
    assert "未在线" in out
    assert "cmcc" in out  # 宿舍网段要给出运营商提示


def test_status_online_json(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    state = fake_portal(monkeypatch)
    state["online"] = True
    assert run(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["online"] is True
    assert payload["sessions"][0]["ours"] is True
    assert payload["sessions"][0]["online_ip"] == IP


def test_check_exit_codes(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = fake_portal(monkeypatch)
    assert run(["check", "-q"]) == 1
    state["online"] = True
    assert run(["check", "-q"]) == 0


def test_status_without_campus(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(net, "reachable", lambda *a, **k: False)
    assert run(["status"]) == 3
    assert "连不上门户" in capsys.readouterr().err


# ---------- login ----------


def test_login_success(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    state = fake_portal(monkeypatch)
    assert run(["login", "-a", "0814", "-p", "pw", "-w", "cmcc"]) == 0
    assert state["logins"] == 1
    out = capsys.readouterr().out
    assert "已在线" in out
    assert ",0,0814@cmcc" in out


def test_login_already_online_skips(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = fake_portal(monkeypatch)
    state["online"] = True
    assert run(["login", "-a", "1", "-p", "p"]) == 0
    assert state["logins"] == 0


def test_login_rejected(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def handler(url: str, _data):
        if "online_list" in url:
            return (200, 'cb({"list":[]})')
        return (200, '{"result":1,"ret_code":1,"msg":"unbind isp uid"}')

    patch_send(monkeypatch, handler)
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert run(["login", "-a", "1", "-p", "p"]) == 1
    out = capsys.readouterr().out
    assert "运营商侧" in out


def test_login_password_stdin(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_portal(monkeypatch)
    monkeypatch.setattr("sys.stdin", type("S", (), {"readline": lambda self: "fromstdin\n"})())
    assert run(["login", "-a", "1", "--password-stdin"]) == 0


def test_login_missing_password(campus: Path, capsys) -> None:
    bare = campus / "bare.toml"
    bare.write_text('adapter = "huuc"\naccount = "0814"\n', encoding="utf-8")
    assert run(["login", "--config", str(bare)]) == 2
    assert "password" in capsys.readouterr().err


def test_unknown_adapter(campus: Path) -> None:
    assert run(["status", "--adapter", "nope"]) == 2


# ---------- install / uninstall ----------


def test_install_dry_run_prints_unit(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(campus / "cfg"))
    monkeypatch.setenv("APPDATA", str(campus / "cfg"))
    assert run(["install", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "campus_auth" in out and "--config" in out
    assert not (campus / "cfg").joinpath("campus-auth").exists()


def test_install_without_config_is_rejected(
    campus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CAMPUS_AUTH_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert run(["install"]) == 2


def test_uninstall_dry_run(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(campus / "cfg"))
    monkeypatch.setenv("APPDATA", str(campus / "cfg"))
    assert run(["uninstall", "--dry-run"]) == 0
    assert "要卸的是" in capsys.readouterr().out


# ---------- urls / logout / unbind ----------


def test_urls_are_encoded(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_portal(monkeypatch)
    assert run(["urls", "-a", "1", "-p", "p", "-o", "out"]) == 0
    files = sorted(p.name for p in (campus / "out").iterdir())
    assert "登录.url" in files
    assert any("cmcc" in name for name in files)
    body = (campus / "out" / "登录.url").read_text(encoding="ascii")
    assert body.startswith("[InternetShortcut]")
    # IP 字符异或后的密文里不会有明文 IP
    assert IP not in body


def test_logout_and_unbind(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_portal(monkeypatch)
    assert run(["logout"]) == 0
    assert run(["unbind", "-a", "1", "-p", "p"]) == 0


def test_unbind_uses_mac_unbind_path(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    seen: dict[str, object] = {}

    def handler(url: str, data):
        seen["url"] = url
        seen["data"] = data
        return (200, '{"result":1,"ret_code":0,"msg":"解绑成功"}')

    patch_send(monkeypatch, handler)
    assert run(["unbind", "-a", "0814"]) == 0
    assert "/eportal/portal/mac/unbind" in str(seen["url"])
    assert seen["data"] is None  # 解绑是 GET
    assert "解绑成功" in capsys.readouterr().out


def test_login_then_logout_in_separate_runs(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    state = fake_portal(monkeypatch)
    assert run(["login", "-a", "0814", "-p", "pw"]) == 0
    assert state["logins"] == 1
    assert run(["logout", "-a", "0814"]) == 0
    assert "服务端: ok" in capsys.readouterr().out


def test_logout_hint_does_not_repeat_the_message(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        Portal, "request", lambda self, request: {"result": 0, "ret_code": 1, "msg": "没收录的新错"}
    )
    assert run(["logout", "-a", "0814"]) == 1
    out = capsys.readouterr().out
    assert out.count("没收录的新错") == 1


# ---------- password / keyring ----------


def test_password_stores_for_adapter_and_account(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    saved: dict[str, str] = {}

    def fake_set(adapter: str, account: str, password: str) -> bool:
        saved.update(adapter=adapter, account=account, password=password)
        return True

    monkeypatch.setattr(credentials, "set", fake_set)
    assert run(["password", "-p", "s3cret"]) == 0
    assert saved == {"adapter": "huuc", "account": "0814", "password": "s3cret"}
    assert "已存入" in capsys.readouterr().out


def test_password_status(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "get", lambda *_a: "abcdef")
    assert run(["password", "--show"]) == 0
    assert "6 位" in capsys.readouterr().out


def test_password_status_when_empty(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "get", lambda *_a: "")
    assert run(["password", "--show"]) == 1
    assert "没有存密码" in capsys.readouterr().out


def test_password_forget(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    dropped: list[tuple[str, str]] = []
    monkeypatch.setattr(credentials, "delete", lambda a, acc: dropped.append((a, acc)) or True)
    assert run(["password", "--forget"]) == 0
    assert dropped == [("huuc", "0814")]


def test_password_without_keyring(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *_a: False)
    assert run(["password", "-p", "p"]) == 3


def test_login_remember_saves_password(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(credentials, "set", lambda a, acc, p: saved.append((a, acc, p)) or True)
    fake_portal(monkeypatch)
    assert run(["login", "-a", "0814", "-p", "pw", "--remember"]) == 0
    assert saved == [("huuc", "0814", "pw")]
    assert "钥匙串" in capsys.readouterr().out


def test_login_remember_failure_is_not_fatal(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "set", lambda *_a: False)
    fake_portal(monkeypatch)
    assert run(["login", "-a", "0814", "-p", "pw", "--remember"]) == 0
    assert "钥匙串存不进去" in capsys.readouterr().out


# ---------- watch --log ----------


def test_watch_writes_log_file(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_portal(monkeypatch)
    assert run(["watch", "--once", "--log", "w.log"]) == 0
    assert "已重新登录" in (campus / "w.log").read_text(encoding="utf-8")


def test_watch_log_still_prints(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_portal(monkeypatch)
    assert run(["watch", "--once", "--log", "w.log"]) == 0
    assert "已重新登录" in capsys.readouterr().out


def test_unbind_transport_error_prints_hint(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """门户回 HTML 时别再甩 200 字符原文，给一句人话。"""
    from campus_auth.errors import TransportError

    patch_send(monkeypatch, lambda _url, _data: TransportError("没有可解析的 JSON"))
    assert run(["unbind", "-a", "0814"]) == 4
    out = capsys.readouterr().out
    assert "解绑失败" in out
    assert "eportal 入口" in out


def test_password_prompts_on_tty(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import cli, commands, credentials

    saved: list[str] = []
    monkeypatch.setattr(credentials, "set", lambda a, acc, p: saved.append(p) or True)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(commands.getpass, "getpass", lambda _prompt: "typed")
    assert run(["password"]) == 0
    assert saved == ["typed"]


def test_password_reads_stdin_when_not_tty(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import cli, credentials

    saved: list[str] = []
    monkeypatch.setattr(credentials, "set", lambda a, acc, p: saved.append(p) or True)
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        type("S", (), {"isatty": lambda self: False, "readline": lambda self: "piped\n"})(),
    )
    assert run(["password"]) == 0
    assert saved == ["piped"]


def test_password_empty_input(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import cli

    monkeypatch.setattr(
        cli.sys,
        "stdin",
        type("S", (), {"isatty": lambda self: False, "readline": lambda self: "\n"})(),
    )
    assert run(["password"]) == 2


# ---------- status 的自我核对 ----------


def test_status_without_account_fails_fast(campus: Path, capsys) -> None:
    bare = campus / "bare2.toml"
    bare.write_text('adapter = "huuc"\n', encoding="utf-8")
    assert run(["status", "--config", str(bare)]) == 2
    assert "还没填 account" in capsys.readouterr().out


def test_status_marks_foreign_session_on_my_ip(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake_portal(monkeypatch)
    foreign = f'cb({{"list":[{{"online_ip":"{IP}","user_account":"别人的号"}}]}})'
    patch_send(monkeypatch, lambda _url, _data: (200, foreign))
    assert run(["status"]) == 1
    out = capsys.readouterr().out
    assert "（别人）" in out
    assert "不是 0814" in out


def test_status_marks_my_session(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_portal(monkeypatch)
    own = f'cb({{"list":[{{"online_ip":"{IP}","user_account":"0814"}}]}})'
    patch_send(monkeypatch, lambda _url, _data: (200, own))
    assert run(["status"]) == 0
    assert "（你）" in capsys.readouterr().out


def test_login_is_not_skipped_when_ip_has_a_foreign_session(
    campus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = fake_portal(monkeypatch)
    state["online"] = True
    ours = {"now": False}

    def handler(url: str, _data):
        if "online_list" in url:
            account = "0814" if ours["now"] else "别人的号"
            return (200, f'cb({{"list":[{{"online_ip":"{IP}","user_account":"{account}"}}]}})')
        ours["now"] = True
        state["logins"] += 1
        return (200, '{"result":1,"ret_code":0,"msg":"认证成功"}')

    patch_send(monkeypatch, handler)
    assert run(["login", "-a", "0814", "-p", "pw"]) == 0
    assert state["logins"] == 1


# ---------- 错误分类与退出码 ----------


def test_check_maps_transport_error_to_4(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth.errors import TransportError

    patch_send(monkeypatch, lambda _url, _data: TransportError("超时"))
    assert run(["check", "-q"]) == 4


def test_check_maps_parse_error_to_1(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    patch_send(monkeypatch, lambda _url, _data: (200, "<html>改版了</html>"))
    assert run(["check", "-q"]) == 1


def test_broken_pipe_exits_quietly(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_args):
        raise BrokenPipeError()

    monkeypatch.setattr(cli, "cmd_adapters", boom)
    assert cli.main(["adapters"]) == 0


def test_windows_invalid_argument_is_not_a_crash(
    campus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_args):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(cli, "cmd_adapters", boom)
    assert cli.main(["adapters"]) == 0


def test_other_oserror_still_crashes(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_args):
        raise OSError(2, "No such file")

    monkeypatch.setattr(cli, "cmd_adapters", boom)
    assert cli.main(["adapters"]) == 70


def test_urls_warn_about_password_in_shortcuts(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake_portal(monkeypatch)
    assert run(["urls", "-a", "1", "-p", "p", "-o", "out"]) == 0
    assert "等于给出密码" in capsys.readouterr().out


def test_show_secrets_turns_off_masking(campus: Path) -> None:
    from campus_auth import commands
    from campus_auth.cli import _parser

    assert commands._config(_parser().parse_args(["status"])).mask_urls is True
    args = _parser().parse_args(["--show-secrets", "status"])
    assert commands._config(args).mask_urls is False


def test_install_requires_account(campus: Path, capsys) -> None:
    bare = campus / "noacct.toml"
    bare.write_text('adapter = "huuc"\n', encoding="utf-8")
    assert run(["install", "--config", str(bare)]) == 2
    assert "account" in capsys.readouterr().err


def test_status_json_keeps_any_online_for_old_scripts(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """1.0 起 online 只说“你自己在线”；旧脚本要的“门户里有人”改看 any_online。"""
    fake_portal(monkeypatch)
    body = f'cb({{"list":[{{"online_ip":"{IP}","user_account":"别人的号"}}]}})'
    patch_send(monkeypatch, lambda _url, _data: (200, body))
    assert run(["status", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["online"] is False
    assert payload["any_online"] is True


# ---------- 帮助信息 ----------


def test_probe_help_does_not_show_password_flags(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["probe", "--help"])
    out = capsys.readouterr().out
    assert "--password-stdin" not in out
    assert "--url" in out


def test_status_help_hides_password_flags(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["status", "--help"])
    out = capsys.readouterr().out
    # argparse 的选项渲染各版本不同（3.11 是 "-a 学号, --account 学号"），只认长名
    assert "--password" not in out
    assert "--account" in out


def test_every_subcommand_has_a_description() -> None:
    import argparse

    parser = cli._parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, child in sub.choices.items():
        assert child.description, f"{name} 缺 description"
        assert len(child.description) > 10


# ---------- watch 的可观测性 ----------


def test_watch_prints_startup_summary(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake_portal(monkeypatch)
    assert run(["watch", "--once"]) == 0
    out = capsys.readouterr().out
    assert "适配层 huuc" in out
    assert "账号 0814" in out


def test_watch_prints_cycle_duration(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import re

    fake_portal(monkeypatch)
    assert run(["watch", "--once"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"#1 .+（\d+\.\d+s）", out), out


def parse_json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    found: list[dict] = []
    index = text.find("{")
    while index != -1:
        obj, end = decoder.raw_decode(text, index)
        found.append(obj)
        index = text.find("{", end)
    return found


def test_watch_json_has_start_and_elapsed(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake_portal(monkeypatch)
    assert run(["watch", "--once", "--json"]) == 0
    events = parse_json_objects(capsys.readouterr().out)
    assert any(e.get("event") == "start" and e["adapter"] == "huuc" for e in events)
    cycle = next(e for e in events if e.get("event") == "cycle")
    assert isinstance(cycle["elapsed_ms"], int)
