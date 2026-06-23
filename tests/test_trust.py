"""Trust 층 테스트 — conformal 캘리브/집합 + 신뢰도·OOD 게이트. 순수·오프라인."""
from __future__ import annotations

from app.trust import (
    aps_set,
    assess,
    conformal_quantile,
    lac_calibrate,
    lac_set,
)

CLASSES = ["crazing", "inclusion", "patches", "pitted_surface", "rolled-in_scale", "scratches"]


def _confident():  # scratches 0.9, 나머지 미미
    p = [0.02] * 6
    p[5] = 0.9
    return p


def test_conformal_quantile_monotone():
    scores = [0.1, 0.2, 0.3, 0.4, 0.5]
    q90 = conformal_quantile(scores, alpha=0.1)
    q50 = conformal_quantile(scores, alpha=0.5)
    assert q90 >= q50  # 더 높은 커버리지 → 더 큰 q̂


def test_lac_calibrate_and_set():
    # 잘 맞는 모델: true 확률이 높음 → s=1-p_true 작음 → q̂ 작음 → 집합 희소.
    cal_probs = [_confident() for _ in range(20)]
    cal_labels = [5] * 20
    qhat = lac_calibrate(cal_probs, cal_labels, alpha=0.1)
    s = lac_set(_confident(), qhat)
    assert s == [5]  # 단일 예측집합


def test_aps_set_includes_crossing_class():
    probs = [0.5, 0.3, 0.2, 0.0, 0.0, 0.0]
    s = aps_set(probs, qhat=0.7)
    # 누적 0.5(<0.7 포함) → 0.8(직전 0.5<0.7 포함) → 직전 0.8≥0.7 중단.
    assert set(s) == {0, 1}


def test_assess_confident_singleton_passes():
    d = assess(_confident(), CLASSES, qhat=0.85, conf_gate=0.8)
    assert d.pred_class == "scratches"
    assert not d.needs_human and not d.ood and not d.ambiguous
    assert d.conformal_set == ["scratches"]


def test_assess_low_confidence_is_ood():
    probs = [0.3, 0.25, 0.2, 0.1, 0.1, 0.05]  # 최대 0.3 < 0.8
    d = assess(probs, CLASSES, qhat=0.85, conf_gate=0.8)
    assert d.ood and d.needs_human


def test_assess_ambiguous_set():
    # 두 클래스가 임계(1-q̂=0.15) 넘음 → 집합 크기 2 → 애매.
    probs = [0.45, 0.45, 0.04, 0.02, 0.02, 0.02]
    d = assess(probs, CLASSES, qhat=0.85, conf_gate=0.4)
    assert d.ambiguous and d.needs_human and len(d.conformal_set) == 2
