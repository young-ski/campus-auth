"""真实 `--json` 输出必须过 `docs/json.schema.json`，文档不能吹牛。

`--json` 是稳定接口：stdout 只有对象，人读文案全在 stderr。这里按最严的形态校验。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_transport import patch_send
from json_schema_check import validate

from campus_auth import cli, probe
from campus_auth.commands import scan
from campus_auth.errors import TransportError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs" / "json.schema.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "json.md").read_text(encoding="utf-8")
IP = "10.138.14.27"


@pytest.fixture
def campus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAMPUS_AUTH_CONFIG", raising=False)
    config = tmp_path / "cfg.toml"
    config.write_text('adapter = "huuc"\naccount = "0814"\npassword = "pw"\n', encoding="utf-8")
    monkeypatch.setenv("CAMPUS_AUTH_CONFIG", str(config))
    monkeypatch.setattr("campus_auth.net.local_ip", lambda *a, **k: IP)
    monkeypatch.setattr("campus_auth.net.local_mac", lambda ip=None: "aabbccddeeff")
    monkeypatch.setattr("campus_auth.net.current_ssid", lambda: "UCSIG")
    monkeypatch.setattr("campus_auth.net.reachable", lambda *a, **k: True)
    monkeypatch.setattr("campus_auth.net.resolves", lambda host: False)
    return tmp_path


def only(text: str) -> dict:
    """stdout 必须是单个 JSON 对象：首字符就是 `{`，整段可解析。"""
    assert text.lstrip().startswith("{"), f"stdout 不是纯 JSON: {text[:120]!r}"
    return json.loads(text)


def objects(text: str) -> list[dict]:
    """watch 是多对象流；仍然要求每一段都是对象、且开头就是对象。"""
    assert text.lstrip().startswith("{"), f"stdout 不是纯 JSON: {text[:120]!r}"
    decoder = json.JSONDecoder()
    found: list[dict] = []
    index = text.find("{")
    while index != -1:
        obj, end = decoder.raw_decode(text, index)
        found.append(obj)
        index = text.find("{", end)
    return found


def check_payloads(payloads: list[dict]) -> None:
    assert payloads, "没有输出任何 JSON"
    for payload in payloads:
        assert payload["schema"] == 1
        errors = validate(payload, SCHEMA)
        assert not errors, f"{errors}\n{json.dumps(payload, ensure_ascii=False)}"


def run(argv: list[str]) -> int:
    return cli.main(argv)


def test_probe_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    analysis = probe.analyze({"body": "城市热点 Dr.COM dr1003 enc_pwd getkey"})
    monkeypatch.setattr(scan, "probe", lambda url, **kw: (analysis, url))
    run(["probe", "--json", "--url", "http://10.0.0.1"])
    check_payloads([only(capsys.readouterr().out)])


def test_probe_error_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """探不到也要有对象，退出码按错误类型走（传输 = 4）。"""

    def boom(url, **kw):
        raise TransportError("一条探针都没通")

    monkeypatch.setattr(scan, "probe", boom)
    assert run(["probe", "--json", "--url", "http://10.0.0.1"]) == 4
    payload = only(capsys.readouterr().out)
    assert payload["ok"] is False
    check_payloads([payload])


def test_status_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    body = f'cb({{"list":[{{"online_ip":"{IP}","user_account":"0814"}}]}})'
    patch_send(monkeypatch, lambda _url, _data: (200, body))
    run(["status", "--json"])
    check_payloads([only(capsys.readouterr().out)])


def test_login_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    state = {"online": False}

    def handler(url: str, _data):
        if "online_list" in url:
            rows = f'[{{"online_ip":"{IP}","user_account":"0814"}}]' if state["online"] else "[]"
            return (200, f'cb({{"list":{rows}}})')
        state["online"] = True
        return (200, 'cb({"result":1,"ret_code":0,"msg":"认证成功"})')

    patch_send(monkeypatch, handler)
    run(["login", "--json", "-p", "pw"])
    payload = only(capsys.readouterr().out)
    assert payload["already_online"] is False
    check_payloads([payload])


def test_login_already_online_still_emits_payload(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """已在线的提前返回曾经一个对象都不出。"""
    body = f'cb({{"list":[{{"online_ip":"{IP}","user_account":"0814"}}]}})'
    patch_send(monkeypatch, lambda _url, _data: (200, body))
    assert run(["login", "--json", "-p", "pw"]) == 0
    payload = only(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["already_online"] is True
    check_payloads([payload])


def test_check_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    patch_send(monkeypatch, lambda _url, _data: (200, 'cb({"list":[]})'))
    assert run(["check", "--json"]) == 1
    payload = only(capsys.readouterr().out)
    assert payload["online"] is False
    check_payloads([payload])


def test_logout_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    patch_send(monkeypatch, lambda _url, _data: (200, '{"result":1,"msg":"注销成功"}'))
    run(["logout", "--json"])
    check_payloads([only(capsys.readouterr().out)])


def test_unbind_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    patch_send(monkeypatch, lambda _url, _data: (200, '{"result":1,"msg":"解绑成功"}'))
    run(["unbind", "--json"])
    check_payloads([only(capsys.readouterr().out)])


def test_unbind_error_payload(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    patch_send(monkeypatch, lambda _url, _data: (200, "<html>门户改版了</html>"))
    run(["unbind", "--json"])
    payloads = objects(capsys.readouterr().out)
    check_payloads(payloads)
    assert payloads[0]["ok"] is False


def test_watch_payloads(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    state = {"online": False}

    def handler(url: str, _data):
        if "online_list" in url:
            rows = f'[{{"online_ip":"{IP}","user_account":"0814"}}]' if state["online"] else "[]"
            return (200, f'cb({{"list":{rows}}})')
        state["online"] = True
        return (200, 'cb({"result":1,"ret_code":0,"msg":"认证成功"})')

    patch_send(monkeypatch, handler)
    assert run(["watch", "--once", "--json"]) == 0
    payloads = objects(capsys.readouterr().out)
    check_payloads(payloads)
    assert {p["event"] for p in payloads} == {"start", "cycle"}


def test_error_payload(
    campus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    bare = tmp_path / "bare.toml"
    bare.write_text('adapter = "huuc"\n', encoding="utf-8")
    assert run(["status", "--json", "--config", str(bare)]) == 2
    check_payloads([only(capsys.readouterr().out)])


def test_doc_mentions_every_json_command() -> None:
    for command in ("probe", "status", "login", "logout", "unbind", "watch", "check"):
        assert f"## `{command} --json" in DOC or f"`{command} --json`" in DOC, command


def test_doc_lists_unsupported_commands() -> None:
    """六条不支持的命令要在文档里点名，别让人试。"""
    for command in ("init", "adapters", "urls", "password", "install", "uninstall"):
        assert f"`{command}`" in DOC, command


def test_missing_config_error_payload(capsys, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAMPUS_AUTH_CONFIG", str(tmp_path / "nope.toml"))
    assert run(["status", "--json"]) == 2
    check_payloads([only(capsys.readouterr().out)])


def test_status_json_stdout_stays_pure(
    campus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """没填 account 时也别在 JSON 之前掺人读文案。"""
    bare = tmp_path / "bare.toml"
    bare.write_text('adapter = "huuc"\n', encoding="utf-8")
    run(["status", "--json", "--config", str(bare)])
    captured = capsys.readouterr()
    assert captured.out.lstrip().startswith("{")
    assert "account" in captured.err
