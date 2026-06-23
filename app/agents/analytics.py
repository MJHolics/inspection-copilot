"""Analytics (NL2SQL) 에이전트 — 자연어 → 검사 DB SQL 생성·검증·실행·요약.

흐름(= `nl2sql-analytics-agent` 패턴을 검사 SQLite DB에 이식):
  스키마 그라운딩 → LLM SQL 생성 → SELECT 전용 가드레일 → dry-run 검증
  → (실패 시 오류 피드백으로 1회 자기수정) → 실행 → 결정적 요약.

LLM은 주입 가능(`sql_llm(system, user) -> str`). 미주입 시 지연 LLM() 사용. 키가 없으면
needs_human=True로 멈춘다(라우팅·트레이싱은 그대로 동작). 요약은 LLM 없이 결정적으로 만든다.
"""
from __future__ import annotations

from .. import db
from ..sqlutils import dry_run, extract_sql, is_safe_select
from .base import AgentRequest, AgentResult, BaseAgent, Evidence

_SYSTEM = (
    "너는 검사 데이터 분석가다. 아래 SQLite 스키마에 대해 사용자의 질문을 답하는 "
    "단일 SELECT 쿼리만 출력한다. 설명 없이 SQL만, SELECT 전용, 변경 쿼리 금지.\n\n{schema}"
)


def _default_llm():
    """지연 생성 LLM 콜러블. 키 없으면 호출 시 RuntimeError."""
    from ..llm import LLM

    client = LLM()
    return lambda system, user: client.complete(system, user, temperature=0.0)


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

    def __init__(self, sql_llm=None, db_path: str | None = None, max_rows: int = 50) -> None:
        self._sql_llm = sql_llm
        self.db_path = db_path or db.DB_PATH
        self.max_rows = max_rows

    def run(self, req: AgentRequest) -> AgentResult:
        try:
            llm = self._sql_llm or _default_llm()
        except Exception as e:  # 키 없음 등 → 멈춤
            return AgentResult(
                agent=self.name, ok=False, summary=f"LLM 사용 불가: {e}",
                confidence=0.0, needs_human=True, error="no_llm",
            )

        conn = db.connect(self.db_path)
        try:
            system = _SYSTEM.format(schema=db.schema_card())
            sql = extract_sql(llm(system, req.text))
            repaired = False

            safe, why = is_safe_select(sql)
            if not safe:
                return AgentResult(
                    agent=self.name, ok=False, summary=f"안전하지 않은 SQL 거부: {why}",
                    evidence=[Evidence(source="guardrail", detail=sql)],
                    confidence=0.0, needs_human=True, error="unsafe_sql",
                )

            ok, err = dry_run(conn, sql)
            if not ok:
                # 오류 피드백으로 1회 자기수정.
                fix_prompt = f"{req.text}\n\n이전 SQL이 실패했다:\n{sql}\n오류: {err}\n고친 SELECT만 출력."
                sql = extract_sql(llm(system, fix_prompt))
                repaired = True
                safe, why = is_safe_select(sql)
                if not safe:
                    return AgentResult(
                        agent=self.name, ok=False, summary=f"자기수정 후도 안전하지 않음: {why}",
                        evidence=[Evidence(source="guardrail", detail=sql)],
                        confidence=0.0, needs_human=True, error="unsafe_sql",
                    )
                ok, err = dry_run(conn, sql)
                if not ok:
                    return AgentResult(
                        agent=self.name, ok=False, summary=f"dry-run 검증 실패: {err}",
                        evidence=[Evidence(source="dry-run", detail=sql)],
                        confidence=0.0, needs_human=True, error="invalid_sql",
                    )

            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchmany(self.max_rows)]
            summary = self._summarize(req.text, cols, rows, repaired)
            return AgentResult(
                agent=self.name, ok=True, summary=summary,
                evidence=[Evidence(source="inspection-db", detail=sql)],
                confidence=0.9 if not repaired else 0.75,
                needs_human=False,
                data={"sql": sql, "columns": cols, "rows": rows, "repaired": repaired},
            )
        finally:
            conn.close()

    @staticmethod
    def _summarize(question: str, cols: list[str], rows: list[dict], repaired: bool) -> str:
        """LLM 없이 결정적 요약(상위 몇 행 + 건수). 신뢰성·테스트 용이."""
        if not rows:
            return "조건에 맞는 행이 없습니다."
        head = rows[:3]
        preview = "; ".join(", ".join(f"{k}={v}" for k, v in r.items()) for r in head)
        tail = f" 외 {len(rows) - 3}건" if len(rows) > 3 else ""
        note = " (자기수정됨)" if repaired else ""
        return f"{len(rows)}행 반환{note}. 상위: {preview}{tail}"
