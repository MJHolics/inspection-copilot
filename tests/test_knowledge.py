"""Knowledge(RAG) 에이전트 테스트 — 그라운딩·근거 게이트·LLM 폴백. 오프라인."""
from __future__ import annotations

from app.agents import AgentRequest
from app.agents.knowledge import KnowledgeAgent


def test_grounded_answer_cites_source():
    res = KnowledgeAgent().run(AgentRequest(text="스크래치 결함은 어떤 절차로 처리해?"))
    assert res.ok and not res.needs_human
    assert res.data["grounded"] is True
    assert res.data["top_source"] == "scratches"
    assert res.evidence and res.evidence[0].source == "scratches"


def test_grounding_gate_stops_on_offtopic():
    # 근거가 약한 질문 → needs_human(환각 대신 멈춤).
    res = KnowledgeAgent().run(AgentRequest(text="점심 메뉴 뭐가 좋아 날씨도 알려줘"))
    assert res.needs_human is True
    assert res.data["grounded"] is False


def test_llm_used_when_injected():
    def fake_llm(system, user):
        assert "근거" in system  # 근거가 컨텍스트로 주입됐는지
        return "요약된 답입니다."

    res = KnowledgeAgent(llm=fake_llm).run(AgentRequest(text="크레이징 원인과 조치는?"))
    assert res.ok and res.summary == "요약된 답입니다."


def test_llm_failure_falls_back_to_extractive():
    def boom(system, user):
        raise RuntimeError("llm down")

    res = KnowledgeAgent(llm=boom).run(AgentRequest(text="개재물 판정 기준 알려줘"))
    assert res.ok and res.data["grounded"] is True
    assert "근거 문서" in res.summary  # 추출형 폴백
