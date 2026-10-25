from __future__ import annotations

import json
from pathlib import Path

import pytest

from campus_auth import cli, commands, probe
from campus_auth.errors import TransportError
from campus_auth.probe import Analysis, Signal, analyze, to_json

DRCOM_SAMPLES = {
    "body": 'probe1003({"result":1,"ret_code":0,"list":[]})',
    "js": ("jsonp('dr1003',{}) function getkey(ip){} function enc_pwd(s,k){} jsVersion encrypt"),
    "headers": "server: nginx\nset-cookie: JSESSIONID=abc",
}

RUIJIE_SAMPLES = {
    "body": (
        '<form action="/eportal/portal/login"><input name="userAccount"><input name="userPassword">'
    ),
}

SRUN_SAMPLES = {"body": '<script src="/cgi-bin/srun_portal?x=1"></script> 深澜认证'}


def test_drcom_is_detected() -> None:
    analysis = analyze(DRCOM_SAMPLES, server="nginx", port=802)
    assert analysis.is_drcom
    assert analysis.verdict == "drcom"
    assert analysis.confidence == "高"


def test_dr_callback_literal_alone_is_medium() -> None:
    analysis = analyze({"js": "jsonp('dr1003', {})"})
    assert analysis.verdict == "likely-drcom"
    assert analysis.confidence == "低"


def test_jsonp_echo_alone_is_not_enough() -> None:
    """回显 callback 只说明是 JSONP 接口，锐捷也这样。"""
    analysis = analyze({"body": 'probe1003({"result":1})'})
    assert analysis.verdict == "likely-drcom"
    assert analysis.confidence == "低"


def test_ruijie_is_not_drcom() -> None:
    analysis = analyze(RUIJIE_SAMPLES)
    assert analysis.verdict == "ruijie"
    assert not analysis.is_drcom


def test_srun_is_not_drcom() -> None:
    analysis = analyze(SRUN_SAMPLES)
    assert analysis.verdict == "srun"
    assert not analysis.is_drcom


def test_ruijie_wins_over_drcom_noise() -> None:
    """锐捷也会回显 callback、也吐 result/ret_code，不能让 Dr.COM 抢了判定。"""
    noisy = {
        "body": (
            '<form action="/eportal/InterFace.do?method=login"><input name="userAccount">'
            ' probe1003({"result":1,"ret_code":0})'
        )
    }
    analysis = analyze(noisy)
    assert analysis.verdict == "ruijie"
    assert not analysis.is_drcom


def test_camel_case_alone_is_not_enough_for_certainty() -> None:
    """只有驼峰参数、没有 InterFace.do 时还在门槛上，别急着给"是锐捷"。"""
    assert analyze({"body": '<input name="userAccount">'}).verdict == "ruijie"
    assert analyze({}).verdict == "unknown"


def test_eportal_alone_is_unknown() -> None:
    analysis = analyze({"body": '<a href="/eportal/portal/login">登录</a>'})
    assert analysis.verdict == "unknown"
    assert any("锐捷" in note for note in analysis.notes)


def test_empty_samples() -> None:
    analysis = analyze({})
    assert analysis.verdict == "unknown"
    assert "没拿到任何响应" in analysis.missing[0]


def test_likely_drcom_band() -> None:
    analysis = analyze({"body": "wlan_user_ip jsVersion <form>"})
    assert analysis.verdict == "likely-drcom"
    assert analysis.is_drcom


def test_missing_listed_when_not_confident() -> None:
    analysis = analyze({"body": "wlan_user_ip jsVersion"})
    assert analysis.verdict == "likely-drcom"
    assert analysis.missing
    assert any("enc_pwd" in item for item in analysis.missing)


def test_evidence_has_weights_and_hits() -> None:
    analysis = analyze(DRCOM_SAMPLES)
    assert all(isinstance(s, Signal) and s.weight > 0 for s in analysis.evidence)
    assert any(s.hit for s in analysis.evidence)


def test_no_false_positive_on_router_page() -> None:
    analysis = analyze({"body": "<html>TP-LINK 路由器管理</html>"})
    assert not analysis.is_drcom
    assert analysis.verdict == "unknown"


def test_json_shape() -> None:
    payload = json.loads(to_json(analyze(DRCOM_SAMPLES), "http://x"))
    assert payload["target"] == "http://x"
    assert payload["is_drcom"] is True
    assert "evidence" in payload


# ---------- CLI ----------


@pytest.fixture
def campus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAMPUS_AUTH_CONFIG", raising=False)
    return tmp_path


def fake_probe(monkeypatch: pytest.MonkeyPatch, analysis: Analysis) -> None:
    monkeypatch.setattr(commands, "probe", lambda url, **kw: (analysis, url))


def test_probe_success(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_probe(monkeypatch, analyze(DRCOM_SAMPLES))
    assert cli.main(["probe", "--url", "http://10.0.0.1:8080"]) == 0
    out = capsys.readouterr().out
    assert "Dr.COM" in out
    assert "huuc" in out


def test_probe_ruijie(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_probe(monkeypatch, analyze(RUIJIE_SAMPLES))
    assert cli.main(["probe", "--url", "http://10.0.0.1"]) == 1
    assert "锐捷" in capsys.readouterr().out


def test_probe_json(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_probe(monkeypatch, analyze(DRCOM_SAMPLES))
    assert cli.main(["probe", "--url", "http://10.0.0.1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["is_drcom"] is True


def test_probe_offline(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def boom(url, **kw):
        raise TransportError("一条探针都没通")

    monkeypatch.setattr(commands, "probe", boom)
    assert cli.main(["probe", "--url", "http://10.0.0.1"]) == 3
    out = capsys.readouterr()
    assert "校园网内" in out.err + out.out


def test_probe_uses_adapter_url(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def grab(url, **kw):
        seen["url"] = url
        return analyze(DRCOM_SAMPLES), url

    monkeypatch.setattr(commands, "probe", grab)
    cli.main(["probe"])
    assert seen["url"] == "https://netauth.huuc.edu.cn:802"


def test_collect_rejects_bad_url() -> None:
    with pytest.raises(Exception, match="看不懂的地址"):
        probe.collect("nonsense")


def test_collect_follows_captive_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """锐捷的根页面只是 location.href 跳转，指纹在被指过去的页面上。"""
    captive = "http://10.0.0.1/eportal/index.jsp?wlanuserip=10.1.2.3"
    pages = {
        "http://10.0.0.1/": f"<script>location.href='{captive}'</script>",
        captive: '<script src="/eportal/js/x.js"></script><form>锐捷</form>',
        "http://10.0.0.1/eportal/js/x.js": "InterFace.do userIndex",
    }

    def fake_fetch(url, _ctx, _timeout, limit=probe.MAX_BODY):
        if url not in pages:
            raise TransportError(url)
        return pages[url], {"server": "nginx"}

    monkeypatch.setattr(probe, "_fetch", fake_fetch)
    samples, _server, _port = probe.collect("http://10.0.0.1")
    assert "锐捷" in samples["body"]
    assert "InterFace.do" in samples["js"]
    assert analyze(samples).verdict == "ruijie"


def test_collect_asks_ruijie_inter_face(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def fake_fetch(url, _ctx, _timeout, limit=probe.MAX_BODY):
        asked.append(url)
        return "", {}

    monkeypatch.setattr(probe, "_fetch", fake_fetch)
    probe.collect("http://10.0.0.1")
    assert any("InterFace.do" in url for url in asked)
    assert any("index.jsp" in url for url in asked)
