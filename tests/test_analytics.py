"""Analytics 에이전트 end-to-end — 주입한 가짜 LLM으로 NL2SQL 전 과정 검증. 오프라인."""
from __future__ import annotations

from app import db
from app.agents import AgentRequest
from app.agents.analytics import AnalyticsAgent


def _agent(tmp_path, sql_llm):
    p = str(tmp_path / "ana.db")
    db.rebuild_db(p, n_rows=300, seed=1)
    return AnalyticsAgent(sql_llm=sql_llm, db_path=p)


def test_happy_path(tmp_path):
    # 가짜 LLM이 유효한 SELECT를 돌려주면 실행·요약까지.
    def llm(system, user):
        return "```sql\nSELECT line, count(*) AS n FROM inspections GROUP BY line ORDER BY n DESC```"

    res = _agent(tmp_path, llm).run(AgentRequest(text="라인별 검사 건수"))
    assert res.ok and not res.needs_human
    assert res.data["rows"]
    assert res.data["sql"].lower().startswith("select")
    assert "행 반환" in res.summary


def test_unsafe_sql_rejected(tmp_path):
    def llm(system, user):
        return "DELETE FROM inspections"

    res = _agent(tmp_path, llm).run(AgentRequest(text="다 지워줘"))
    assert not res.ok and res.needs_human and res.error == "unsafe_sql"


def test_self_repair_on_bad_column(tmp_path):
    # 1차는 잘못된 컬럼 → dry-run 실패 → 2차에 올바른 SQL로 자기수정.
    calls = {"n": 0}

    def llm(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return "SELECT bogus_col FROM inspections"
        return "SELECT count(*) AS n FROM inspections"

    res = _agent(tmp_path, llm).run(AgentRequest(text="총 검사 건수"))
    assert res.ok
    assert res.data["repaired"] is True
    assert res.confidence < 0.9  # 자기수정이면 신뢰도 하향
    assert calls["n"] == 2


def test_no_llm_key_needs_human(tmp_path):
    # sql_llm 미주입 + 키 없음 → 멈춤(needs_human), 라우팅·트레이싱은 깨지지 않음.
    import os

    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(k, None)
    p = str(tmp_path / "nk.db")
    db.rebuild_db(p, n_rows=50, seed=1)
    res = AnalyticsAgent(db_path=p).run(AgentRequest(text="건수"))
    assert not res.ok and res.needs_human and res.error == "no_llm"
