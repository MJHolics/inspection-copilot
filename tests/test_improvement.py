"""자가개선 루프 — 검토 큐·재학습 트리거·승격 게이트 단위테스트(순수·결정적)."""
from __future__ import annotations

from app.improvement import (
    ModelStats,
    ReviewQueue,
    evaluate_promotion,
    should_retrain,
)


class _FakeResult:
    def __init__(self, needs_human, steps, confs):
        self.needs_human = needs_human
        self.plan = type("P", (), {"steps": steps})()
        self.results = [type("R", (), {"confidence": c})() for c in confs]


def test_queue_ingests_only_needs_human():
    q = ReviewQueue()
    assert q.ingest(_FakeResult(True, ["knowledge"], [0.0])) is True
    assert q.ingest(_FakeResult(False, ["analytics"], [0.9])) is False
    assert len(q.items) == 1


def test_corrected_count_and_retrain_trigger():
    q = ReviewQueue()
    for _ in range(3):
        q.ingest(_FakeResult(True, ["knowledge"], [0.0]))
    q.correct(0, "scratches")
    q.correct(1, "crazing")
    assert q.corrected_count == 2
    assert should_retrain(q.corrected_count, threshold=2) is True
    assert should_retrain(q.corrected_count, threshold=5) is False
    assert should_retrain(0, drift_alert=True) is True  # 드리프트로도 트리거


# VLM Defect Inspector 실측 모델 스탯(현행 v4 기준선)
V4 = ModelStats("v4", type_acc=0.959, risk_score=0.0041)


def test_gate_rejects_more_accurate_but_unsafe():
    """v5: 정확도 99.3%(최고)인데 위험 회귀(0.0074>0.0041) → 거부."""
    d = evaluate_promotion(V4, ModelStats("v5", type_acc=0.993, risk_score=0.0074))
    assert d.promote is False and "안전 회귀" in d.reason


def test_gate_promotes_risk_tie_with_accuracy_gain():
    """v7: 위험 동률(0.0041)·정확도 +3%p(98.9%) → 승격(≤ 만족)."""
    d = evaluate_promotion(V4, ModelStats("v7", type_acc=0.989, risk_score=0.0041))
    assert d.promote is True and "승격" in d.reason


def test_gate_rejects_accuracy_regression():
    """위험은 통과(동률)지만 정확도가 퇴보하면 거부."""
    d = evaluate_promotion(V4, ModelStats("vX", type_acc=0.90, risk_score=0.0041))
    assert d.promote is False and "정확도 퇴보" in d.reason
