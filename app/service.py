"""공유 supervisor 팩토리 — 서버·데모·CLI가 동일 인스턴스를 지연 생성해 쓴다."""
from __future__ import annotations

from pathlib import Path

from .agents import default_registry
from .supervisor import Supervisor

_sup: Supervisor | None = None

# 체크포인트 기본 위치. 요청마다 파일 하나(run_id.json).
RUNS_DIR = Path("runs")


def get_supervisor() -> Supervisor:
    """데모·서빙용 supervisor — 가능하면 실 ONNX 비전 모델을 주입(없으면 안전 멈춤).

    그라운딩 검색기는 config.GROUNDING_RETRIEVER로 선택(tfidf 기본 / dense 의미검색).
    """
    global _sup
    if _sup is None:
        from .retrieval import make_grounding_retriever
        from .router import default_llm_router
        from .vision_model import load_default_predictor

        kn_retriever, tau = make_grounding_retriever()  # config 기반(tfidf | dense)
        agents = default_registry(vision_predictor=load_default_predictor(),
                                  knowledge_retriever=kn_retriever, grounding_tau=tau)
        # 키가 있으면 실 LLM 라우터, 없으면 Supervisor 기본(RuleRouter)으로 자동 폴백.
        _sup = Supervisor(agents=agents, router=default_llm_router())
    return _sup


def get_durable_supervisor(run_id: str, runs_dir: Path | None = None,
                           fsync: bool = False, budget_s: float | None = None):
    """같은 에이전트 구성에 내구 실행 층을 씌운 supervisor(요청 1건 = 체크포인트 파일 1개).

    `get_supervisor()`와 **같은 레지스트리·라우터**를 쓴다 — 측정한 구성과 배포된 구성이 갈리지
    않게 하려는 기존 원칙 그대로다. 기본 `fsync=False`는 위협 모델이 프로세스 사망(OOM 킬·컨테이너
    교체)이기 때문이고, 전원 손실까지 막아야 하면 True로 켠다(단계당 1.37ms → 3.41ms).

    같은 run_id로 다시 부르면 끝난 단계는 재실행하지 않고, 완료된 요청이면 저장된 결과를 재생한다.
    """
    from .durable import DurableSupervisor, FileCheckpointStore, RetryPolicy

    base = get_supervisor()
    store = FileCheckpointStore((runs_dir or RUNS_DIR) / f"{run_id}.json", fsync=fsync)
    return DurableSupervisor(agents=base.agents, router=base.router, tracer=base.tracer,
                             store=store, retry=RetryPolicy(), budget_s=budget_s)


def result_to_dict(res) -> dict:
    """SupervisorResult → JSON 직렬화 가능한 dict(서버 응답·데모 공용)."""
    from . import config

    return {
        "answer": res.answer,
        "ok": res.ok,
        "needs_human": res.needs_human,
        "route": res.plan.steps,
        "router": res.plan.router,
        "reason": res.plan.reason,
        "grounding_retriever": config.GROUNDING_RETRIEVER,  # 데모 배지: 어휘(tfidf) vs 의미(dense)
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
