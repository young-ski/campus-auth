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

    def fake_get(self: Portal, path: str, params):
        state["calls"].append(path)
        if path.endswith("online_list"):
            return {"list": [{"online_ip": IP, "user_account": "0814"}] if state["online"] else []}
        if path.endswith("login"):
            state["logins"] += 1
            state["online"] = online_after_login
            return {"result": 1, "ret_code": 0, "msg": "认证成功"}
        return {"result": 1, "msg": "ok"}

    monkeypatch.setattr(Portal, "get", fake_get)
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
    def fake_get(self, path, params):
        if path.endswith("online_list"):
            return {"list": []}
        return {"result": 1, "ret_code": 1, "msg": "unbind isp uid"}

    monkeypatch.setattr(Portal, "get", fake_get)
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
