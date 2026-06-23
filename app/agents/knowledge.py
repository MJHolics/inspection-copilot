"""Knowledge (RAG) 에이전트 — 검사 표준·SOP 문서를 검색해 답을 그라운딩한다.

흐름: 코퍼스 로드(캐시) → retriever 검색 → **근거 거리 게이트**(최상위 유사도가 임계 미만이면
"관련 근거 부족"으로 신뢰도 하향 + needs_human) → 그라운딩 답 생성.

답 생성은 기본 추출형(top 근거 청크의 핵심 + 출처 인용)이라 LLM 없이도 동작·테스트된다.
LLM을 주입하면 근거를 컨텍스트로 받아 요약 답을 생성한다(환각 방지: 근거 밖 주장 금지 지시).
retriever도 주입 가능 — 기본은 TF-IDF 베이스라인, 벡터(BGE-M3/Chroma)로 교체 가능.
"""
from __future__ import annotations

from ..retrieval import KeywordRetriever, load_corpus
from .base import AgentRequest, AgentResult, BaseAgent, Evidence

# 최상위 유사도가 이보다 낮으면 근거 부족으로 보고 멈춘다(환각 대신 사람검토).
GROUNDING_TAU = 0.06

_SYSTEM = (
    "너는 검사 표준 안내자다. 아래 근거(SOP 발췌)에만 기반해 한국어로 간결히 답하라. "
    "근거에 없는 내용은 추측하지 말고 '근거 없음'이라고 말하라.\n\n근거:\n{context}"
)


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

    def __init__(self, retriever=None, llm=None, k: int = 3, tau: float = GROUNDING_TAU) -> None:
        self._retriever = retriever  # None이면 첫 호출 때 코퍼스로 빌드
        self._llm = llm
        self.k = k
        self.tau = tau

    def _get_retriever(self):
        if self._retriever is None:
            self._retriever = KeywordRetriever(load_corpus())
        return self._retriever

    def run(self, req: AgentRequest) -> AgentResult:
        retriever = self._get_retriever()
        hits = retriever.search(req.text, k=self.k)
        top = hits[0].score if hits else 0.0

        evidence = [
            Evidence(source=h.chunk.source, detail=h.chunk.title, score=round(h.score, 4))
            for h in hits if h.score > 0
        ]

        # 근거 거리 게이트: 관련 근거가 약하면 멈춘다(환각 방지).
        if not hits or top < self.tau:
            return AgentResult(
                agent=self.name, ok=True,
                summary="관련 근거를 찾지 못했습니다. 사람 검토 또는 질문 구체화가 필요합니다.",
                evidence=evidence, confidence=round(top, 3), needs_human=True,
                data={"hits": [(h.chunk.source, round(h.score, 4)) for h in hits], "grounded": False},
            )

        answer = self._answer(req.text, hits)
        return AgentResult(
            agent=self.name, ok=True, summary=answer, evidence=evidence,
            confidence=round(min(1.0, top), 3), needs_human=False,
            data={
                "hits": [(h.chunk.source, round(h.score, 4)) for h in hits],
                "grounded": True,
                "top_source": hits[0].chunk.source,
            },
        )

    def _answer(self, question: str, hits) -> str:
        """근거 기반 답. LLM 있으면 요약, 없으면 추출형(top 근거 발췌 + 출처)."""
        context = "\n\n".join(f"[{h.chunk.source}] {h.chunk.text}" for h in hits)
        if self._llm is not None:
            try:
                return self._llm(_SYSTEM.format(context=context), question).strip()
            except Exception:
                pass  # LLM 실패 시 추출형으로 폴백
        # 추출형(LLM 없을 때): 최상위 근거의 본문 앞부분 + 출처 인용.
        top = hits[0].chunk
        body = " ".join(line for line in top.text.splitlines() if line and not line.startswith("#"))
        snippet = body[:200] + ("…" if len(body) > 200 else "")
        return f"근거 문서 '{top.source}'({top.title}) 기준: {snippet}"
