"""공유 supervisor 팩토리 — 서버·데모·CLI가 동일 인스턴스를 지연 생성해 쓴다."""
from __future__ import annotations

from .supervisor import Supervisor

_sup: Supervisor | None = None


def get_supervisor() -> Supervisor:
    global _sup
    if _sup is None:
        _sup = Supervisor()
    return _sup


def result_to_dict(res) -> dict:
    """SupervisorResult → JSON 직렬화 가능한 dict(서버 응답·데모 공용)."""
    return {
        "answer": res.answer,
        "ok": res.ok,
        "needs_human": res.needs_human,
        "route": res.plan.steps,
        "router": res.plan.router,
        "reason": res.plan.reason,
        "agents": [
            {
                "agent": r.agent,
                "ok": r.ok,
                "summary": r.summary,
                "confidence": r.confidence,
                "needs_human": r.needs_human,
                "evidence": [{"source": e.source, "detail": e.detail, "score": e.score} for e in r.evidence],
            }
            for r in res.results
        ],
        "report_markdown": next(
            (r.data.get("markdown") for r in res.results if r.agent == "report"), None
        ),
        "latency_ms": res.trace.total_latency_ms if res.trace else None,
    }
