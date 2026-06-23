"""합성 검사 데이터베이스 — Analytics(NL2SQL) 에이전트가 질의할 SQLite DB.

공개 데이터셋이 없으므로 NEU 표면결함 6종을 본떠 결정적으로(시드 고정) 생성한다. 같은 시드면
항상 같은 행이 나와 테스트·데모가 재현 가능하다. 스키마는 현장에서 흔한 형태(검사 이벤트 단위:
시점·제품·라인·결함클래스·심각도·신뢰도·사람검토여부)로 두어 NL2SQL 질문이 자연스럽게 나오게 했다.
"""
from __future__ import annotations

import os
import random
import sqlite3

from . import config

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "inspection.db")

_LINES = ("L1", "L2", "L3")
_PRODUCTS = ("steel_coil", "steel_plate", "steel_strip")
_SEVERITY = ("low", "medium", "high")

SCHEMA_SQL = """
CREATE TABLE inspections (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,   -- 검사 일자 'YYYY-MM-DD'
    product       TEXT NOT NULL,   -- 제품군: steel_coil | steel_plate | steel_strip
    line          TEXT NOT NULL,   -- 생산 라인: L1 | L2 | L3
    defect_class  TEXT NOT NULL,   -- 결함 클래스(NEU 6종) 또는 'none'(양품)
    severity      TEXT,            -- low | medium | high (양품이면 NULL)
    confidence    REAL NOT NULL,   -- 모델 신뢰도 0~1
    reviewed      INTEGER NOT NULL -- 사람 검토 완료 여부 0/1
);
"""


def schema_card() -> str:
    """LLM SQL 생성용 스키마 그라운딩 텍스트(컬럼 의미·허용값·예시 질문)."""
    classes = ", ".join(config.DEFECT_CLASSES)
    return (
        "테이블 inspections — 표면결함 검사 이벤트 1건당 1행.\n"
        "컬럼:\n"
        "  id INTEGER, ts TEXT('YYYY-MM-DD'), product TEXT, line TEXT,\n"
        f"  defect_class TEXT(결함 6종: {classes}; 양품은 'none'),\n"
        "  severity TEXT(low|medium|high; 양품은 NULL), confidence REAL(0~1), reviewed INTEGER(0|1)\n"
        "규칙: SELECT 전용. 날짜 필터는 ts 문자열 비교(예: ts >= '2026-06-01').\n"
        "예시 질문: 'L2 라인에서 가장 많은 결함은?', '이번 달 high 심각도 불량 건수', "
        "'제품별 불량률'."
    )


def build_db(path: str = DB_PATH, n_rows: int = 600, seed: int = 42) -> str:
    """결정적 합성 DB를 (재)생성하고 경로를 반환. 이미 있으면 그대로 둔다."""
    if os.path.exists(path):
        return path
    return rebuild_db(path, n_rows, seed)


def rebuild_db(path: str = DB_PATH, n_rows: int = 600, seed: int = 42) -> str:
    """항상 새로 생성(테스트·리셋용)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    rng = random.Random(seed)
    classes = list(config.DEFECT_CLASSES)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        rows = []
        for i in range(1, n_rows + 1):
            # 60% 양품, 40% 불량 — 라인별로 불량 경향을 살짝 다르게(L3이 불량 많게).
            line = rng.choice(_LINES)
            defect_bias = {"L1": 0.30, "L2": 0.38, "L3": 0.52}[line]
            is_defect = rng.random() < defect_bias
            if is_defect:
                dc = rng.choice(classes)
                sev = rng.choices(_SEVERITY, weights=(5, 3, 2))[0]
                conf = round(rng.uniform(0.55, 0.99), 3)
            else:
                dc, sev, conf = "none", None, round(rng.uniform(0.80, 0.999), 3)
            month = rng.choice(("04", "05", "06"))
            day = rng.randint(1, 28)
            ts = f"2026-{month}-{day:02d}"
            reviewed = 1 if (sev == "high" or rng.random() < 0.2) else 0
            rows.append((i, ts, rng.choice(_PRODUCTS), line, dc, sev, conf, reviewed))
        conn.executemany(
            "INSERT INTO inspections VALUES (?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()
    finally:
        conn.close()
    return path


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """읽기용 연결(없으면 빌드). row_factory로 dict 접근 가능."""
    build_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
