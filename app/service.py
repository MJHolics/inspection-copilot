"""공유 supervisor 팩토리 — 서버·데모·CLI가 동일 인스턴스를 지연 생성해 쓴다."""
from __future__ import annotations

from .agents import default_registry
from .supervisor import Supervisor

_sup: Supervisor | None = None


def get_supervisor() -> Supervisor:
    """데모·서빙용 supervisor — 가능하면 실 ONNX 비전 모델을 주입(없으면 안전 멈춤)."""
    global _sup
    if _sup is None:
        from .router import default_llm_router
        from .vision_model import load_default_predictor

        agents = default_registry(vision_predictor=load_default_predictor())
        # 키가 있으면 실 LLM 라우터, 없으면 Supervisor 기본(RuleRouter)으로 자동 폴백.
        _sup = Supervisor(agents=agents, router=default_llm_router())
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
