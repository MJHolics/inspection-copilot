"""트레이스 요약 지표 단위테스트 — 순수 함수라 네트워크 없이 검증."""
from __future__ import annotations

from app.trace import RequestTrace, StepRecord, summarize


def _rec(route, ok=True, needs_human=False, latency=100):
    return RequestTrace(
        ts="t", request="q", router="rule", route=route,
        steps=[StepRecord(agent=a, ok=True, latency_ms=10) for a in route],
        total_latency_ms=latency, ok=ok, needs_human=needs_human,
    ).to_dict()


def test_summarize_empty():
    assert summarize([]) == {"count": 0}


def test_summarize_metrics():
    recs = [
        _rec(["knowledge"], ok=True, latency=100),
        _rec(["vision", "report"], ok=True, needs_human=True, latency=200),
        _rec(["analytics"], ok=False, latency=300),
    ]
    s = summarize(recs)
    assert s["count"] == 3
    assert s["success_rate"] == round(2 / 3, 3)
    assert s["human_review_rate"] == round(1 / 3, 3)
    assert s["avg_steps"] == round((1 + 2 + 1) / 3, 2)
    assert s["latency_ms_p50"] >= 100


def test_route_distribution():
    recs = [_rec(["knowledge"]), _rec(["knowledge"]), _rec(["vision", "report"])]
    s = summarize(recs)
    assert s["route_distribution"]["knowledge"] == 2
    assert s["route_distribution"]["vision>report"] == 1
