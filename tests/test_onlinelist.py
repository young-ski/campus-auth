"""onlinelist：网段展开、并发扫描、CSV 导出与退出码。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fake_transport import patch_send

from campus_auth import cli, net
from campus_auth.adapters import get_adapter
from campus_auth.errors import ConfigError, TransportError
from campus_auth.onlinelist import expand, parse_targets, scan
from campus_auth.portal import Portal

IP = "10.138.14.27"


@pytest.fixture
def campus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAMPUS_AUTH_PASSWORD", raising=False)
    config = tmp_path / "cfg.toml"
    config.write_text('adapter = "huuc"\naccount = "0814"\n', encoding="utf-8")
    monkeypatch.setenv("CAMPUS_AUTH_CONFIG", str(config))
    monkeypatch.setattr(net, "local_ip", lambda host, port=80, timeout=5: IP)
    monkeypatch.setattr(net, "local_mac", lambda ip=None: "aabbccddeeff")
    monkeypatch.setattr(net, "current_ssid", lambda: "UCLINK")
    monkeypatch.setattr(net, "reachable", lambda *a, **k: True)
    monkeypatch.setattr(net, "resolves", lambda host: False)
    return tmp_path


def run(argv: list[str]) -> int:
    return cli.main(argv)


def by_ip(url: str) -> str:
    matched = re.search(r"wlan_user_ip=([^&]+)", url)
    assert matched, url
    return matched.group(1)


# ---------- 网段展开 ----------


def test_expand_accepts_cidr_wildcard_and_span() -> None:
    assert expand("10.1.2.3") == ["10.1.2.3"]
    assert len(expand("10.1.2.*")) == 254
    assert expand("10.1.2.5-7") == ["10.1.2.5", "10.1.2.6", "10.1.2.7"]
    assert expand("10.1.2.9-10.1.2.10") == ["10.1.2.9", "10.1.2.10"]
    assert expand("") == []


def test_expand_skips_network_and_broadcast() -> None:
    addresses = expand("10.1.2.0/30")
    assert addresses == ["10.1.2.1", "10.1.2.2"]


def test_expand_rejects_nonsense() -> None:
    for spec in ("10.1.2.999", "10.1.2.9-3", "10.1.2.0/33", "::1"):
        with pytest.raises(ConfigError):
            expand(spec)


def test_parse_targets_dedupes_and_keeps_order() -> None:
    assert parse_targets(["10.1.2.3", "10.1.2.1-3"]) == [
        "10.1.2.3",
        "10.1.2.1",
        "10.1.2.2",
    ]


# ---------- 扫描本身 ----------


def portal() -> Portal:
    return Portal(get_adapter("huuc"), ip=IP, mac="aabbccddeeff", account="0814")


def test_scan_collects_only_online_rows() -> None:
    def handler(url: str, _data):
        if by_ip(url) == "10.1.2.1":
            return (200, 'cb({"result":1,"list":[{"online_ip":"10.1.2.1","user_account":"a"}]})')
        if by_ip(url) == "10.1.2.2":
            return (200, 'cb({"result":0,"msg":"异常"})')
        return (200, 'cb({"result":1,"list":[{"online_ip":"10.1.2.3","user_account":"b"}]})')

    p = portal()
    with pytest.MonkeyPatch.context() as mp:
        patch_send(mp, handler)
        outcome = scan(p, p.adapter, ["10.1.2.2", "10.1.2.3", "10.1.2.1"], workers=2)

    assert [session.ip for session in outcome.sessions] == ["10.1.2.1", "10.1.2.3"]
    assert outcome.scanned == 3
    assert outcome.failed == 0


def test_scan_counts_a_failed_address() -> None:
    def handler(url: str, _data):
        if by_ip(url) == "10.1.2.2":
            raise TransportError("超时")
        return (200, 'cb({"list":[]})')

    p = portal()
    with pytest.MonkeyPatch.context() as mp:
        patch_send(mp, handler)
        outcome = scan(p, p.adapter, ["10.1.2.1", "10.1.2.2"], workers=2)

    assert outcome.scanned == 2
    assert outcome.failed == 1
    assert outcome.failed_ips == ["10.1.2.2"]
    assert outcome.sessions == []


# ---------- 命令层 ----------


def test_onlinelist_uses_the_adapter_range(campus: Path, monkeypatch, capsys) -> None:
    from campus_auth.commands import onlinelist
    from campus_auth.onlinelist import ScanOutcome

    seen: dict[str, list[str]] = {}

    def fake_scan(_portal, _adapter, targets, **_kw):
        seen["targets"] = targets
        return ScanOutcome()

    monkeypatch.setattr(onlinelist, "scan", fake_scan)
    assert run(["onlinelist", "-q"]) == 0
    assert len(seen["targets"]) == 65534  # 10.152.0.0/16 去掉网络号与广播


def test_onlinelist_needs_a_range_for_generic(campus: Path, capsys) -> None:
    assert run(["onlinelist", "--adapter", "generic", "-q"]) == 2
    assert "--range" in capsys.readouterr().err


def test_onlinelist_exports_csv(campus: Path, monkeypatch, capsys) -> None:
    body = (
        'cb({"result":1,"list":[{"online_ip":"10.1.2.1","user_account":"x",'
        '"online_mac":"aabb","time_long":"65","online_time":"2026-11-17 10:00:00"}]})'
    )
    patch_send(monkeypatch, lambda _url, _data: (200, body))
    assert run(["onlinelist", "-r", "10.1.2.1", "-q", "-e", "out.csv"]) == 0
    raw = (campus / "out.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # Excel 打开不乱码
    text = raw.decode("utf-8-sig")
    assert "IP,账号,MAC,上线时间,在线秒数,本机" in text
    assert "10.1.2.1,x,aabb,2026-11-17 10:00:00,65,0" in text
    assert "CSV 已写到" in capsys.readouterr().err


def test_onlinelist_csv_to_stdout(campus: Path, monkeypatch, capsys) -> None:
    patch_send(monkeypatch, lambda _url, _data: (200, 'cb({"list":[]})'))
    assert run(["onlinelist", "-r", "10.1.2.1", "-q", "-e", "-"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("IP,账号")


def test_onlinelist_csv_stdout_and_json_conflict(campus: Path, monkeypatch) -> None:
    assert run(["onlinelist", "-r", "10.1.2.1", "-e", "-", "--json"]) == 2


def test_onlinelist_json_marks_the_local_session(campus: Path, monkeypatch, capsys) -> None:
    body = (
        f'cb({{"result":1,"list":[{{"online_ip":"{IP}","user_account":"0814","time_long":"5"}}]}})'
    )
    patch_send(monkeypatch, lambda _url, _data: (200, body))
    assert run(["onlinelist", "-r", IP, "-q", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["sessions"][0]["ours"] is True
    assert payload["sessions"][0]["seconds"] == 5
    assert payload["ranges"] == [IP]


def test_onlinelist_table_marks_own_row(campus: Path, monkeypatch, capsys) -> None:
    body = (
        f'cb({{"result":1,"list":[{{"online_ip":"{IP}","user_account":"0814","time_long":"5"}}]}})'
    )
    patch_send(monkeypatch, lambda _url, _data: (200, body))
    assert run(["onlinelist", "-r", IP, "-q"]) == 0
    out = capsys.readouterr().out
    assert "*" in out and "0814" in out


def test_onlinelist_reports_total_failure_as_transport(campus: Path, monkeypatch, capsys) -> None:
    def boom(_url, _data):
        raise TransportError("没网")

    patch_send(monkeypatch, boom)
    assert run(["onlinelist", "-r", "10.1.2.1", "-q"]) == 4
    assert "最终失败" in capsys.readouterr().err


def test_onlinelist_retries_a_failed_address(campus: Path, monkeypatch, capsys) -> None:
    calls = {"n": 0}

    def handler(_url, _data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransportError("超时")
        return (200, 'cb({"result":1,"list":[{"online_ip":"10.1.2.1","user_account":"x"}]})')

    patch_send(monkeypatch, handler)
    assert run(["onlinelist", "-r", "10.1.2.1", "-q"]) == 0
    assert calls["n"] == 2
    captured = capsys.readouterr()
    assert "重试" in captured.err
    assert captured.out.count("10.1.2.1") == 1  # 重试拿回来的行不重复


def test_onlinelist_retry_zero_keeps_the_failure(campus: Path, monkeypatch, capsys) -> None:
    calls = {"n": 0}

    def handler(_url, _data):
        calls["n"] += 1
        raise TransportError("超时")

    patch_send(monkeypatch, handler)
    assert run(["onlinelist", "-r", "10.1.2.1", "--retry", "0", "-q", "--json"]) == 4
    assert calls["n"] == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed_ips"] == ["10.1.2.1"]
    assert payload["retried"] == 0
    assert payload["ok"] is False


def test_onlinelist_json_counts_retries(campus: Path, monkeypatch, capsys) -> None:
    calls = {"n": 0}

    def handler(_url, _data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransportError("超时")
        return (200, 'cb({"list":[]})')

    patch_send(monkeypatch, handler)
    assert run(["onlinelist", "-r", "10.1.2.1", "-q", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["retried"] == 1
    assert payload["failed"] == 0 and payload["failed_ips"] == []


def test_onlinelist_help_has_export_and_no_password_flag(capsys) -> None:
    with pytest.raises(SystemExit):
        run(["onlinelist", "--help"])
    out = capsys.readouterr().out
    assert "--export" in out
    assert "--password" not in out


def test_onlinelist_rejects_a_bad_output_path(campus: Path, monkeypatch, capsys) -> None:
    patch_send(monkeypatch, lambda _url, _data: (200, 'cb({"list":[]})'))
    (campus / "blocker").write_text("x", encoding="utf-8")
    assert run(["onlinelist", "-r", "10.1.2.1", "-q", "-e", "blocker/x.csv"]) == 2
    assert "写不了 CSV" in capsys.readouterr().err
