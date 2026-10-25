from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    """把 Portal.get 换成有状态的假实现。"""
    state = {"online": False, "logins": 0, "calls": []}

    def fake_request(self: Portal, request):
        state["calls"].append(request.path)
        if request.path.endswith("online_list"):
            return {"list": [{"online_ip": IP, "user_account": "0814"}] if state["online"] else []}
        if request.path.endswith("login"):
            state["logins"] += 1
            state["online"] = online_after_login
            return {"result": 1, "ret_code": 0, "msg": "认证成功"}
        return {"result": 1, "msg": "ok"}

    monkeypatch.setattr(Portal, "request", fake_request)
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
    def fake_request(self, request):
        if request.path.endswith("online_list"):
            return {"list": []}
        return {"result": 1, "ret_code": 1, "msg": "unbind isp uid"}

    monkeypatch.setattr(Portal, "request", fake_request)
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
    assert "campus_auth watch --config" in out
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


def test_unbind_ruijie_goes_to_interface(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    # 直接给 index.jsp，解绑时才不用真去撞 204 劫持页
    config = campus / "ruijie.toml"
    config.write_text(
        'adapter = "ruijie"\naccount = "20240001"\n'
        'base_url = "http://1.2.3.4/eportal/index.jsp?service=x"\n',
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def fake_request(self: Portal, request):
        seen["path"] = request.path
        seen["body"] = dict(request.body)
        return {"result": "success", "message": "解绑成功"}

    monkeypatch.setattr(Portal, "request", fake_request)
    assert run(["unbind", "--config", str(config)]) == 0
    assert str(seen["path"]).endswith("InterFace.do?method=unbind")
    assert seen["body"]["userId"] == "20240001"
    assert "解绑成功" in capsys.readouterr().out


def test_logout_ruijie_in_a_later_process(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """login 和 logout 是两次独立运行：userIndex 只能靠落盘传过去。"""
    config = campus / "ruijie.toml"
    config.write_text(
        'adapter = "ruijie"\naccount = "20240001"\n'
        'base_url = "http://1.2.3.4/eportal/index.jsp?service=x"\n',
        encoding="utf-8",
    )
    server = {"index": "", "seq": 0}

    def fake_request(self: Portal, request):
        if "method=login" in request.path:
            server["seq"] += 1
            server["index"] = f"idx{server['seq']}"
            return {"result": "success", "userIndex": server["index"]}
        if "method=logout" in request.path:
            if request.body["userIndex"] != server["index"]:
                return {"result": "fail", "message": "未登录"}
            return {"result": "success", "message": "注销成功"}
        return {}

    monkeypatch.setattr(Portal, "request", fake_request)
    # 别去撞真 204：登录过程中和 login 之后都会问一次在线与否
    monkeypatch.setattr(Portal, "raw", lambda *a, **k: ((204 if server["index"] else 200), ""))

    assert run(["login", "--config", str(config), "-p", "pw"]) == 0
    assert run(["logout", "--config", str(config)]) == 0
    # 缓存注销成功后就被丢掉了，再注销一次只能拿空 userIndex 去撞
    assert run(["logout", "--config", str(config)]) == 1
    assert "userIndex" in capsys.readouterr().out


def test_logout_hint_does_not_repeat_the_message(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config = campus / "ruijie.toml"
    config.write_text(
        'adapter = "ruijie"\naccount = "20240001"\n'
        'base_url = "http://1.2.3.4/eportal/index.jsp?service=x"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        Portal, "request", lambda self, request: {"result": "fail", "message": "没收录的新错"}
    )
    assert run(["logout", "--config", str(config)]) == 1
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
    assert run(["password"]) == 0
    assert "6 位" in capsys.readouterr().out


def test_password_status_when_empty(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "get", lambda *_a: "")
    assert run(["password"]) == 1
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
    """深澜回 HTML 时别再甩 200 字符原文，给一句人话。"""
    from campus_auth.errors import TransportError

    config = campus / "srun.toml"
    config.write_text('adapter = "srun"\naccount = "20240001"\n', encoding="utf-8")

    def boom(self: Portal, request):
        raise TransportError("响应里没有可解析的 JSON 对象: '<!doctype html>...'")

    monkeypatch.setattr(Portal, "request", boom)
    monkeypatch.setattr(Portal, "raw", lambda *a, **k: (200, "<script>var ac_id='12';</script>"))
    assert run(["unbind", "--config", str(config)]) == 4
    out = capsys.readouterr().out
    assert "解绑失败" in out
    assert "没有解绑接口" in out
