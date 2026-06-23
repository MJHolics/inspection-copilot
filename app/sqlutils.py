"""SQL 가드레일·검증 — 순수 함수라 네트워크·LLM 없이 단위테스트된다.

가드레일: SELECT 전용(DML/DDL 금지)·단일 문장. dry-run: SQLite EXPLAIN으로 실행 없이
문법·컬럼을 컴파일 검증(잘못된 컬럼/문법이면 여기서 잡혀 자기수정 피드백으로 쓰인다).
"""
from __future__ import annotations

import re
import sqlite3

_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "truncate",
)


def extract_sql(text: str) -> str:
    """LLM 출력에서 SQL만 추출. ```sql 펜스/설명 문장 제거."""
    if not text:
        return ""
    m = re.search(r"```(?:sql)?\s*(.+?)```", text, re.DOTALL | re.IGNORECASE)
    sql = m.group(1) if m else text
    return sql.strip().rstrip(";").strip()


def is_safe_select(sql: str) -> tuple[bool, str]:
    """(안전여부, 사유). SELECT/WITH로 시작 + 금지 키워드 없음 + 단일 문장."""
    s = sql.strip()
    if not s:
        return False, "빈 SQL"
    if ";" in s.rstrip(";"):
        return False, "다중 문장 금지(단일 SELECT만 허용)"
    low = re.sub(r"\s+", " ", s.lower())
    if not (low.startswith("select") or low.startswith("with")):
        return False, "SELECT/WITH로 시작하지 않음"
    for kw in _FORBIDDEN:
        if re.search(rf"\b{kw}\b", low):
            return False, f"금지 키워드 사용: {kw}"
    return True, "ok"


def dry_run(conn: sqlite3.Connection, sql: str) -> tuple[bool, str]:
    """EXPLAIN으로 실행 없이 컴파일 검증. (성공여부, 오류메시지)."""
    try:
        conn.execute("EXPLAIN " + sql)
        return True, ""
    except sqlite3.Error as e:
        return False, str(e)
