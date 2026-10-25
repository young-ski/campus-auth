"""拿假门户自己的页面来校准打分 —— 两边一起改，不容易各说各话。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from campus_auth.probe import analyze

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import fake_portal  # noqa: E402

DRCOM_SAMPLES = {
    "body": fake_portal.DRCOM_PAGE + '\nprobe1003({"result":1,"ret_code":0,"list":[]})',
    "js": fake_portal.DRCOM_JS,
}
RUIJIE_SAMPLES = {"body": fake_portal.RUIJIE_PAGE, "js": fake_portal.RUIJIE_JS}


def srun_samples(variant: str) -> dict[str, str]:
    prefix = fake_portal.VARIANTS[variant][0]
    return {"body": fake_portal.SRUN_PAGE % {"ac_id": "12", "enc_ver": variant, "prefix": prefix}}


@pytest.mark.parametrize(
    ("samples", "want"),
    [
        (DRCOM_SAMPLES, "drcom"),
        (RUIJIE_SAMPLES, "ruijie"),
        (srun_samples("srun_bx1"), "srun"),
        (srun_samples("srun_bx2"), "srun"),
    ],
)
def test_fake_markup_gets_the_right_verdict(samples: dict[str, str], want: str) -> None:
    analysis = analyze(samples)
    assert analysis.verdict == want
    assert analysis.confidence == "高"


UNIQUE = {
    "drcom": {"页面 / JS 里出现 dr1003 一类回调", "JS 里有 enc_pwd（异或加密函数）"},
    "ruijie": {"出现 InterFace.do 接口"},
    "srun": {"srun_portal 接口"},
}


@pytest.mark.parametrize(
    ("samples", "want"),
    [
        (DRCOM_SAMPLES, "drcom"),
        (RUIJIE_SAMPLES, "ruijie"),
        (srun_samples("srun_bx1"), "srun"),
    ],
)
def test_decisive_signals_are_what_fires(samples: dict[str, str], want: str) -> None:
    """判对还不够：撑起结论的必须是对家独有那条，不是通用噪声。"""
    hits = {s.name for s in analyze(samples).evidence if s.hit}
    assert hits & UNIQUE[want]


def test_router_page_stays_unknown() -> None:
    assert analyze({"body": "<html>TP-LINK 路由器管理</html>"}).verdict == "unknown"


def test_ambiguous_drcom_and_srun_says_so() -> None:
    samples = {"body": "dr1003 srun_portal"}
    analysis = analyze(samples)
    assert analysis.verdict == "likely-drcom"
    assert any("分不开" in note for note in analysis.notes)


def test_drcom_without_jsversion_is_still_drcom() -> None:
    """老门户没有 jsVersion，别被"eportal 无 jsVersion ≈ 锐捷"带跑。"""
    samples = {
        "body": "城市热点 Dr.COM wlan_user_ip eportal/portal/online_list",
        "js": "function getkey(){} function enc_pwd(){} jsonp('dr1003')",
    }
    assert analyze(samples).verdict == "drcom"
