"""Knowledge (RAG) 에이전트 (P1 스텁).

검사 표준·SOP·결함 처리 지침 문서를 검색해 답을 **그라운딩**한다. 근거 거리(distance)가
임계 밖이면 "관련 근거 부족"으로 신뢰도를 낮추고 사람검토로 넘긴다. P2에서 `multimodal_rag`
(BGE-M3·Chroma·hybrid) 자산을 이식한다.
"""
from __future__ import annotations

from .base import AgentRequest, AgentResult, BaseAgent, Evidence


class KnowledgeAgent(BaseAgent):
    name = "knowledge"
    description = (
        "검사 표준·SOP·결함 처리 지침 문서에서 근거를 찾아 답을 그라운딩한다. "
        "'어떻게 처리/기준/규격/절차/원인' 류 설명 질문에 호출한다. 일반 질문의 기본 폴백."
    )
    keywords = (
        "어떻게", "처리", "기준", "규격", "표준", "절차", "지침", "원인", "조치", "왜",
        "sop", "spec", "standard", "guideline", "이유", "방법", "설명",
    )

    def run(self, req: AgentRequest) -> AgentResult:
        # TODO(P2): BGE-M3 임베딩 → Chroma hybrid 검색 → 거리 게이트 → LLM 그라운딩 답.
        #           top 근거 거리 > tau면 confidence 하향 + needs_human.
        return AgentResult(
            agent=self.name,
            ok=True,
            summary=f"[스텁] '{req.text}' → 검사표준/SOP 검색·그라운딩 답 예정(P2).",
            evidence=[Evidence(source="SOP(예정)", detail="검색 근거 청크(예정)", score=None)],
            confidence=0.0,
            needs_human=False,
            data={"chunks": [], "stub": True},
        )
