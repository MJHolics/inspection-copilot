"""Eval 러너 — 골든 태스크셋에 시스템을 돌려 지표를 수치화한다.

오프라인·결정적으로 측정한다:
  • 라우팅 정확도 — RuleRouter가 기대 라우트를 내는가
  • 그라운딩 충실도 — Knowledge가 기대 SOP 출처에 그라운딩하는가
  • 게이트(가드레일) 정확도 — needs_human이 기대와 일치하는가(근거 부족 시 멈춤)
  • e2e 성공률 — 라우팅·그라운딩·게이트가 모두 기대대로이고 실행이 성공했는가

Analytics는 SQL 생성 LLM을 결정적 스텁으로 주입한다(질문→고정 SQL). 이렇게 하면 LLM의 SQL
'품질'(키 필요·비결정적)이 아니라 **시스템의 SQL 실행 파이프라인**(가드레일·dry-run·실 DB 실행·
요약)을 재현 가능하게 측정한다. 실 LLM 측정은 키를 주입해 sql_llm=None으로 돌리면 된다.
"""
from __future__ import annotations

import json

from .. import db
from ..agents import KnowledgeAgent, ReportAgent, VisionAgent
from ..agents.analytics import AnalyticsAgent
from ..supervisor import Supervisor
from ..trace import Tracer
from .metrics import CaseResult, aggregate, route_exact, route_jaccard
from .tasks import GOLDEN, Task

# 질문 → 고정 SQL(실 DB 실행 파이프라인을 결정적으로 행사). 키 불요.
EVAL_SQL: dict[str, str] = {
    "라인별 불량 건수 알려줘":
        "SELECT line, count(*) AS n FROM inspections WHERE defect_class != 'none' "
        "GROUP BY line ORDER BY n DESC",
    "high 심각도 불량 통계 내줘":
        "SELECT count(*) AS n FROM inspections WHERE severity = 'high'",
    "제품별 평균 신뢰도 추세":
        "SELECT product, round(avg(confidence), 3) AS avg_conf FROM inspections GROUP BY product",
    "라인별 불량 건수 통계로 보고서 만들어줘":
        "SELECT line, count(*) AS n FROM inspections WHERE defect_class != 'none' "
        "GROUP BY line ORDER BY n DESC",
    "이 사진 검사하고 라인별 불량 통계로 보고서 줘":
        "SELECT line, count(*) AS n FROM inspections WHERE defect_class != 'none' GROUP BY line",
    "이번 달 검사 건수 알려줘":
        "SELECT count(*) AS n FROM inspections WHERE ts >= '2026-06-01'",
}


def _stub_sql(system: str, user: str) -> str:
    return EVAL_SQL.get(user, "SELECT count(*) AS n FROM inspections")


def _stub_vision(image_path: str) -> list[float]:
    """결정적 비전 predictor — 자신있는 scratches 예측(trust 게이트 경로를 재현 측정).

    config.DEFECT_CLASSES 순서에 정렬. 최대 신뢰도 0.9(>게이트) + 단일 conformal 집합 → needs_human=False.
    """
    from .. import config

    probs = [0.02] * len(config.DEFECT_CLASSES)
    probs[config.DEFECT_CLASSES.index("scratches")] = 0.9
    return probs


def _build_supervisor(sql_llm, vision_predictor=_stub_vision) -> Supervisor:
    agents = {
        "vision": VisionAgent(predictor=vision_predictor),
        "analytics": AnalyticsAgent(sql_llm=sql_llm),
        "knowledge": KnowledgeAgent(),
        "report": ReportAgent(),
    }
    return Supervisor(agents=agents, tracer=Tracer(path="", echo=False))


def _grounding_correct(results, expected_source: str) -> bool:
    for r in results:
        if r.agent == "knowledge":
            return bool(r.data.get("grounded")) and r.data.get("top_source") == expected_source
    return False


def evaluate_task(sup: Supervisor, task: Task) -> CaseResult:
    res = sup.handle(task.question, image_path=task.image_path)
    pred = res.plan.steps
    r_exact = route_exact(pred, task.expected_route)
    r_jac = route_jaccard(pred, task.expected_route)
    gate_ok = res.needs_human == task.expect_needs_human
    grounding = None
    if task.expected_top_source is not None:
        grounding = _grounding_correct(res.results, task.expected_top_source)
    e2e = bool(r_exact and gate_ok and (grounding in (True, None)) and res.ok)
    return CaseResult(
        id=task.id, route_pred=pred, route_gold=task.expected_route,
        route_exact=r_exact, route_jaccard=round(r_jac, 3), gate_correct=gate_ok,
        grounding_correct=grounding, e2e_success=e2e,
        latency_ms=res.trace.total_latency_ms if res.trace else 0,
    )


def run(tasks: list[Task] | None = None, sql_llm=_stub_sql) -> tuple[list[CaseResult], dict]:
    """골든셋 평가 → (케이스별 결과, 집계 지표). DB는 결정적으로 빌드해둔다."""
    db.build_db()
    sup = _build_supervisor(sql_llm)
    cases = [evaluate_task(sup, t) for t in (tasks or GOLDEN)]
    return cases, aggregate(cases)


def _main() -> None:
    cases, summary = run()
    print("=== 케이스별 ===")
    for c in cases:
        g = "-" if c.grounding_correct is None else ("O" if c.grounding_correct else "X")
        print(
            f"  {c.id:<13} route={'O' if c.route_exact else 'X'} "
            f"gate={'O' if c.gate_correct else 'X'} ground={g} "
            f"e2e={'O' if c.e2e_success else 'X'}  ({'>'.join(c.route_pred)})"
        )
    print("\n=== 집계 지표 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
