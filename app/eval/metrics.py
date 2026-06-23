"""Eval 지표 — 순수 함수라 네트워크 없이 단위테스트된다.

라우팅 정확도(정확일치·자카드), 그라운딩 충실도, 게이트(가드레일) 정확도, e2e 성공률을 집계한다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CaseResult:
    id: str
    route_pred: list[str]
    route_gold: list[str]
    route_exact: bool
    route_jaccard: float
    gate_correct: bool
    grounding_correct: bool | None  # None = 해당 없음(grounding 태스크 아님)
    e2e_success: bool
    latency_ms: int


def route_exact(pred: list[str], gold: list[str]) -> bool:
    return pred == gold


def route_jaccard(pred: list[str], gold: list[str]) -> float:
    a, b = set(pred), set(gold)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return s[i]


def aggregate(cases: list[CaseResult]) -> dict:
    n = len(cases)
    if n == 0:
        return {"count": 0}
    grounding = [c for c in cases if c.grounding_correct is not None]
    lat = [c.latency_ms for c in cases]
    return {
        "count": n,
        "routing_exact_acc": round(sum(c.route_exact for c in cases) / n, 3),
        "routing_jaccard_avg": round(sum(c.route_jaccard for c in cases) / n, 3),
        "gate_acc": round(sum(c.gate_correct for c in cases) / n, 3),
        "grounding_acc": (
            round(sum(bool(c.grounding_correct) for c in grounding) / len(grounding), 3)
            if grounding else None
        ),
        "e2e_success_rate": round(sum(c.e2e_success for c in cases) / n, 3),
        "latency_ms_p50": _percentile(lat, 50),
        "latency_ms_p95": _percentile(lat, 95),
    }
