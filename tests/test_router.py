"""라우터 단위테스트 — 의도에 따라 경로가 달라지는지(고정 체인이 아닌지) 검증. 오프라인."""
from __future__ import annotations

from app.agents import AgentRequest, default_registry
from app.router import LLMRouter, RuleRouter


def _plan(text: str, image_path: str | None = None):
    agents = default_registry()
    return RuleRouter().plan(AgentRequest(text=text, image_path=image_path), agents)


def test_image_routes_to_vision():
    plan = _plan("이 부품 검사해줘", image_path="a.jpg")
    assert "vision" in plan.steps


def test_analytics_intent():
    plan = _plan("지난 달 스크래치 불량 몇 건이야?")
    assert "analytics" in plan.steps


def test_knowledge_intent():
    plan = _plan("스크래치 결함은 어떻게 처리하는 게 표준 절차야?")
    assert "knowledge" in plan.steps


def test_empty_falls_back_to_knowledge():
    plan = _plan("음...")
    assert plan.steps == ["knowledge"]


def test_multi_agent_appends_report_last():
    # 이미지(vision) + 통계(analytics) → 종합 리포트가 마지막에 붙어야 한다.
    plan = _plan("이 사진 불량인지 보고, 이번 달 추세도 같이 봐줘", image_path="a.jpg")
    assert "vision" in plan.steps and "analytics" in plan.steps
    assert plan.steps[-1] == "report"


def test_routes_differ_by_request():
    # 핵심: 같은 시스템이 요청에 따라 서로 다른 경로를 낸다(동적 라우팅).
    a = _plan("불량 처리 절차 알려줘")
    b = _plan("이번 달 불량 건수 통계 내줘")
    assert a.steps != b.steps


def test_explicit_report_request():
    plan = _plan("이번 달 불량 통계로 보고서 만들어줘")
    assert "report" in plan.steps


def test_llm_router_falls_back_without_llm():
    agents = default_registry()
    plan = LLMRouter(llm=None).plan(AgentRequest(text="불량 통계 내줘"), agents)
    assert "analytics" in plan.steps
    assert plan.router == "llm->rule"


def test_llm_router_uses_injected_plan():
    agents = default_registry()

    def fake(text, tools):
        return {"steps": ["knowledge", "report"], "reason": "fake"}

    plan = LLMRouter(llm=fake).plan(AgentRequest(text="아무거나"), agents)
    assert plan.steps == ["knowledge", "report"]
    assert plan.router == "llm"
