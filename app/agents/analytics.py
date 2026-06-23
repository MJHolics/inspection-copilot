"""Analytics (NL2SQL) 에이전트 (P1 스텁).

자연어 → 검사/생산 DB SQL 생성 → **dry-run 검증**(문법·컬럼·비용 가드) → 실행 → 요약.
SELECT 전용·DML 금지 가드레일. P2에서 `nl2sql-analytics-agent` 자산을 검사 DB(NEU 로그
SQLite)에 맞춰 이식한다.
"""
from __future__ import annotations

from .base import AgentRequest, AgentResult, BaseAgent, Evidence


class AnalyticsAgent(BaseAgent):
    name = "analytics"
    description = (
        "검사/생산 데이터베이스에 자연어로 질의한다. 수율·결함 추세·건수·비율 등 집계 질문에 "
        "SQL을 생성·검증·실행해 답한다. 'DB/통계/수율/추세/몇 건' 류 질문에 호출한다."
    )
    keywords = (
        "수율", "통계", "추세", "추이", "몇 건", "몇개", "건수", "비율", "평균", "지난",
        "이번 달", "분포", "가장 많은", "top", "trend", "yield", "count", "rate", "데이터",
    )

    def run(self, req: AgentRequest) -> AgentResult:
        # TODO(P2): RAG 스키마 그라운딩 → LLM SQL 생성 → dry-run 검증 → 실행 → 요약.
        #           SELECT 전용·비용 가드 + 실패 시 1회 자기수정(nl2sql 패턴).
        return AgentResult(
            agent=self.name,
            ok=True,
            summary=f"[스텁] '{req.text}' → 검사 DB SQL 생성·dry-run 검증·실행 예정(P2).",
            evidence=[Evidence(source="inspection-db", detail="생성 SQL(예정)", score=None)],
            confidence=0.0,
            needs_human=False,
            data={"sql": None, "rows": [], "stub": True},
        )
