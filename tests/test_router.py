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


def test_collision_drops_weak_knowledge():
    # 과잉 라우팅 보정: 통계 질문에 '원인'(약한 말)만으로 knowledge가 끌려오면 안 된다.
    plan = _plan("불량 원인별 통계 추세 보여줘")
    assert "analytics" in plan.steps
    assert "knowledge" not in plan.steps           # 약한 말뿐 → 제외
    plan2 = _plan("왜 자꾸 불량이 나는지 데이터로 분석해줘")
    assert plan2.steps == ["analytics"]


def test_collision_keeps_strong_knowledge():
    # 정당한 멀티: 통계 + '조치/방법'(강한 절차 의도)이 함께면 knowledge를 유지한다.
    plan = _plan("수율 낮은 라인의 결함 통계 내고 조치 방법도 알려줘")
    assert "analytics" in plan.steps and "knowledge" in plan.steps
    assert plan.steps[-1] == "report"              # 다중 → 종합 리포트


def test_weak_knowledge_alone_still_routes_knowledge():
    # 보정은 analytics가 함께일 때만. '왜'만 있고 analytics가 없으면 knowledge 정상 라우팅.
    plan = _plan("이 결함은 왜 생겨?")
    assert plan.steps == ["knowledge"]


def test_llm_router_falls_back_without_llm():
    agents = default_registry()
    plan = LLMRouter(complete=None).plan(AgentRequest(text="불량 통계 내줘"), agents)
    assert "analytics" in plan.steps
    assert plan.router == "llm->rule"


def test_llm_router_parses_json_plan():
    agents = default_registry()

    def fake(system, user):
        return '여기 계획: {"steps": ["knowledge", "report"], "reason": "설명 질문+리포트"}'

    plan = LLMRouter(complete=fake).plan(AgentRequest(text="아무거나"), agents)
    assert plan.steps == ["knowledge", "report"]
    assert plan.router == "llm" and plan.reason.startswith("LLM:")


def test_llm_router_forces_vision_on_image():
    agents = default_registry()

    def fake(system, user):  # LLM이 vision을 빠뜨려도 이미지가 있으면 강제.
        return '{"steps": ["analytics"], "reason": "통계"}'

    plan = LLMRouter(complete=fake).plan(
        AgentRequest(text="이 사진 통계", image_path="x.jpg"), agents)
    assert "vision" in plan.steps
    assert plan.steps[-1] == "report"  # 다중 → 종합 보장


def test_llm_router_falls_back_on_bad_json():
    agents = default_registry()

    def boom(system, user):
        return "JSON 아님 그냥 횡설수설"

    plan = LLMRouter(complete=boom).plan(AgentRequest(text="불량 통계"), agents)
    assert plan.router == "llm->rule" and "analytics" in plan.steps


def test_llm_router_falls_back_on_exception():
    agents = default_registry()

    def crash(system, user):
        raise RuntimeError("api down")

    plan = LLMRouter(complete=crash).plan(AgentRequest(text="스크래치 처리 절차"), agents)
    assert plan.router == "llm->rule" and "knowledge" in plan.steps
