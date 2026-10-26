"""拿假门户自己的页面来校准打分 —— 两边一起改，不容易各说各话。"""

from __future__ import annotations

import sys
from pathlib import Path

from campus_auth.probe import analyze

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import fake_portal  # noqa: E402

DRCOM_SAMPLES = {
    "body": fake_portal.DRCOM_PAGE + '\nprobe1003({"result":1,"ret_code":0,"list":[]})',
    "js": fake_portal.DRCOM_JS,
}


def test_fake_markup_is_drcom() -> None:
    analysis = analyze(DRCOM_SAMPLES)
    assert analysis.verdict == "drcom"
    assert analysis.confidence == "高"


def test_decisive_signal_is_what_fires() -> None:
    """判对还不够：撑起结论的必须是对家独有那条，不是通用噪声。"""
    hits = {s.name for s in analyze(DRCOM_SAMPLES).evidence if s.hit}
    assert any("enc_pwd" in name or "dr1003" in name for name in hits)


def test_router_page_stays_unknown() -> None:
    assert analyze({"body": fake_portal.ROUTER_PAGE}).verdict == "unknown"


def test_drcom_without_jsversion_is_still_drcom() -> None:
    """老门户没有 jsVersion，别被"eportal 无 jsVersion ≈ 锐捷"带跑。"""
    samples = {
        "body": "城市热点 Dr.COM wlan_user_ip eportal/portal/online_list",
        "js": "function getkey(){} function enc_pwd(){} jsonp('dr1003')",
    }
    assert analyze(samples).verdict == "drcom"


def test_ambiguous_drcom_and_srun_says_so() -> None:
    analysis = analyze({"body": "dr1003 srun_portal"})
    assert analysis.verdict == "likely-drcom"
    assert any("分不开" in note for note in analysis.notes)
