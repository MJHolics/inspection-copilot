"""Supervisor end-to-end 테스트 — 스텁 에이전트로 라우팅·실행·종합·가드레일 검증. 오프라인."""
from __future__ import annotations

from app.agents import AgentRequest, AgentResult, BaseAgent
from app.supervisor import Supervisor
from app.trace import Tracer


def _silent_supervisor(agents=None):
    # 테스트 중 stdout/파일 트레이싱 끔.
    return Supervisor(agents=agents, tracer=Tracer(path="", echo=False))


def test_handle_returns_synthesized_answer():
    sup = _silent_supervisor()
    res = sup.handle("스크래치 불량 처리 절차 알려줘")
    assert res.ok
    assert "knowledge" in res.plan.steps
    assert "라우팅" in res.answer
    assert res.trace is not None
    assert res.trace.route == res.plan.steps


def test_context_accumulates_to_report():
    # 다중 에이전트 → report가 앞 단계 결과를 context로 받는지.
    sup = _silent_supervisor()
    res = sup.handle("이번 달 불량 통계로 보고서 만들어줘")
    report = [r for r in res.results if r.agent == "report"][0]
    assert report.data["sections"]  # 앞 에이전트(analytics 등)가 채워져 있어야


def test_needs_human_propagates():
    # 한 에이전트가 needs_human이면 supervisor 전체가 needs_human이어야("멈춤" 가드레일).
    class FlakyAgent(BaseAgent):
        name = "knowledge"
        keywords = ("아무거나",)

        def run(self, req: AgentRequest) -> AgentResult:
            return AgentResult(agent="knowledge", ok=True, summary="애매함",
                               confidence=0.1, needs_human=True)

    agents = {"knowledge": FlakyAgent()}
    sup = _silent_supervisor(agents=agents)
    res = sup.handle("아무거나 알려줘")
    assert res.needs_human
    assert "사람 검토" in res.answer


def test_trace_has_per_step_records():
    sup = _silent_supervisor()
    res = sup.handle("이 사진 검사하고 추세 통계도 줘", image_path="x.jpg")
    assert len(res.trace.steps) == len(res.plan.steps)
    assert all(s.latency_ms >= 0 for s in res.trace.steps)
