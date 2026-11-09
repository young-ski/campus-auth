from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_transport import DictTransport

from campus_auth import cli, probe
from campus_auth.commands import scan
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
    monkeypatch.setattr(scan, "probe", lambda url, **kw: (analysis, url))


def test_probe_success(campus: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake_probe(monkeypatch, analyze(DRCOM_SAMPLES))
    assert cli.main(["probe", "--url", "http://10.0.0.1:8080"]) == 0
    out = capsys.readouterr().out
    assert "Dr.COM" in out
    assert "generic" in out


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

    monkeypatch.setattr(scan, "probe", boom)
    # 传输错误按 errors.py 的约定是 4，不是「环境」
    assert cli.main(["probe", "--url", "http://10.0.0.1"]) == 4
    out = capsys.readouterr()
    assert "校园网内" in out.err + out.out


def test_probe_uses_adapter_url(campus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def grab(url, **kw):
        seen["url"] = url
        return analyze(DRCOM_SAMPLES), url

    monkeypatch.setattr(scan, "probe", grab)
    cli.main(["probe", "--no-discover"])
    assert seen["url"] == "https://netauth.huuc.edu.cn:802"


def test_collect_rejects_bad_url() -> None:
    with pytest.raises(Exception, match="看不懂的地址"):
        probe.collect("nonsense")


def test_collect_follows_captive_redirect() -> None:
    """锐捷的根页面只是 location.href 跳转，指纹在被指过去的页面上。"""
    captive = "http://10.0.0.1/eportal/index.jsp?wlanuserip=10.1.2.3"
    transport = DictTransport(
        {
            "http://10.0.0.1/": f"<script>location.href='{captive}'</script>",
            captive: '<script src="/eportal/js/x.js"></script><form>锐捷</form>',
            "http://10.0.0.1/eportal/js/x.js": "InterFace.do userIndex",
        }
    )
    samples, _server, _port = probe.collect("http://10.0.0.1", transport=transport)
    assert "锐捷" in samples["body"]
    assert "InterFace.do" in samples["js"]
    assert analyze(samples).verdict == "ruijie"


def test_collect_asks_inter_face_and_index() -> None:
    transport = DictTransport({})
    with pytest.raises(TransportError):
        probe.collect("http://10.0.0.1", transport=transport)
    assert any("InterFace.do" in url for url in transport.calls)
    assert any("index.jsp" in url for url in transport.calls)


def test_no_follow_skips_captive_hop() -> None:
    """--no-follow 时不跟劫持页给的地址，只留跳转页本身。"""
    transport = DictTransport(
        {"http://10.0.0.1/": "<script>location.href='http://x/eportal/'</script>"}
    )
    samples, _server, _port = probe.collect("http://10.0.0.1", transport=transport, follow=False)
    assert "location.href" in samples["body"]
    assert not any(url == "http://x/eportal/" for url in transport.calls)


def test_probe_notes_the_followed_host() -> None:
    """跟了跳转就在结论里点一句，别让用户以为指纹来自原地址。"""
    captive = "http://portal.example/eportal/index.jsp"
    transport = DictTransport(
        {
            "http://10.0.0.1/": f"<script>location.href='{captive}'</script>",
            captive: "深澜 dr1003 enc_pwd getkey 城市热点",
        }
    )
    analysis, _used = probe.probe("http://10.0.0.1", transport=transport)
    assert any("portal.example" in note for note in analysis.notes)


def test_probe_no_follow_has_no_host_note() -> None:
    transport = DictTransport({"http://10.0.0.1/": "深澜"})
    analysis, _used = probe.probe("http://10.0.0.1", transport=transport, follow=False)
    assert not any("跳转" in note for note in analysis.notes)


def test_probe_bad_url_is_a_config_error(campus: Path, capsys) -> None:
    """地址写错是配置问题（2），别跟「不在校园网」混成一个退出码。"""
    assert cli.main(["probe", "--url", "nonsense"]) == 2
    captured = capsys.readouterr()
    assert "地址" in captured.err
    assert "校园网" not in captured.out


def test_probe_out_of_range_port_is_a_config_error(campus: Path) -> None:
    assert cli.main(["probe", "--url", "http://h:99999"]) == 2


def test_unquoted_script_src_is_followed() -> None:
    """本校门户是 Vue SPA，`src=` 后面没引号；旧正则只认带引号的写法，JS 永远抓不到。"""
    pages = {
        "http://10.0.0.1/": (
            "<div id=app></div><script src=/eportal/public/static/js/app.38f7.js></script>"
        ),
        "http://10.0.0.1/eportal/public/static/js/app.38f7.js": (
            "drcom wlan_user_ip online_session:'x'"
        ),
    }
    samples, _server, _port = probe.collect("http://10.0.0.1", transport=DictTransport(pages))
    assert "drcom" in samples["js"]


def test_fallback_js_is_tried_when_page_links_none() -> None:
    """有的门户把 JS 藏在登录页而不是首页；固定候选补一刀，404 桩要能识别。"""
    transport = DictTransport(
        {
            "http://10.0.0.1/": "<div id=app></div>",
            "http://10.0.0.1/eportal/portal/js/a41.js": (
                'jsonpReturn({"code":0,"msg":"404 eportal action a41.js not found"})'
            ),
            "http://10.0.0.1/eportal/portal/js/portal.js": "enc_pwd getkey wlan_user_ip",
        }
    )
    samples, _server, _port = probe.collect("http://10.0.0.1", transport=transport)
    assert "enc_pwd" in samples["js"]


ONLINE_BODY = (
    'probe1003({"result":1,"msg":"获取用户在线信息成功！","list":[{"online_session":23137,'
    '"online_time":"2026-11-09 20:29:03","online_ip":"10.152.59.163"}],"total":1});'
)


def test_online_session_counts_as_distinctive_evidence() -> None:
    """已在线是多数人首试状态：会话结构本身就是独有证据，别再判成"像"或"不认"。"""
    analysis = analyze({"body": ONLINE_BODY})
    assert analysis.verdict == "drcom"
    assert analysis.is_drcom


def test_online_state_is_named_in_notes() -> None:
    analysis = analyze({"body": ONLINE_BODY})
    assert any("已在线" in note for note in analysis.notes)


def test_http_portal_retries_over_https() -> None:
    """门户只收 HTTPS，按 `http://<IP>` 探会 400；要自动换 https 再探一遍。"""
    from campus_auth.transport import Response

    seen: list[str] = []

    class HttpsOnly:
        def send(self, url: str, **_kwargs) -> Response:
            seen.append(url)
            if url.startswith("http://"):
                return Response(400, "Bad Request", {"server": "nginx"})
            return Response(200, "drcom wlan_user_ip online_session:", {"server": "nginx"})

    analysis, used = probe.probe("http://10.210.213.208:802", transport=HttpsOnly())
    assert analysis.is_drcom
    assert any(url.startswith("https://") for url in seen)
    assert used.startswith("https://")  # 结论里报实际用的地址，别报回跳过的 http


def test_probe_falls_back_to_adapter_url_when_discover_fails(
    campus: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """已在线时劫持页捞不到地址；单校工具已知本校地址，别再把用户推给 --url。"""
    from campus_auth.errors import ConfigError

    def boom(*_args, **_kwargs):
        raise ConfigError("没从劫持页找到门户地址")

    monkeypatch.setattr(scan, "discover_portal", boom)
    seen: dict[str, str] = {}

    def grab(url, **_kwargs):
        seen["url"] = url
        return analyze(DRCOM_SAMPLES), url

    monkeypatch.setattr(scan, "probe", grab)
    assert cli.main(["probe"]) == 0
    captured = capsys.readouterr()
    assert seen["url"] == "https://netauth.huuc.edu.cn:802"
    assert "改用适配层地址" in captured.out + captured.err


def test_probe_retries_a_failing_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--retries` 以前挂在 help 里但没人用。"""
    from fake_transport import DictTransport

    calls = {"n": 0}

    class Flaky(DictTransport):
        def send(self, url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TransportError("超时")
            return super().send(url, **kwargs)

    pages = {
        "http://10.0.0.1/": "城市热点 Dr.COM dr1003 enc_pwd getkey",
        "http://10.0.0.1/eportal/index.jsp": "",
        "http://10.0.0.1/eportal/portal/online_list?callback=probe1003&lang=zh": "",
        "http://10.0.0.1/eportal/InterFace.do?method=getOnlineUserInfo": "",
    }
    analysis, _ = probe.probe("http://10.0.0.1", transport=Flaky(pages), retries=1)
    assert analysis.is_drcom
