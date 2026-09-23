"""SQLite -> PostgreSQL 이식성 실측 — Analytics(NL2SQL) 에이전트의 검사 DB를 두 번째 RDBMS로도 검증.

## 왜 하는가

이 프로젝트(와 저장소 전체)의 관계형 DB 경험이 SQLite(`app/db.py`)뿐이었다. 최근 공고
(㈜파란샘 — PostgreSQL을 스킬 태그로 명시)를 보고 확인한 갭이다. Graph DB(E10)·벡터DB(E27)를
닫을 때와 같은 방법론을 쓴다 — "연결된다"가 아니라 **같은 스키마·같은 데이터·같은 질의에서
같은 답이 나오는가, 그리고 SQLite 전용 문법이 조용히 틀린 답을 내지 않고 dry-run 가드에서
정직하게 걸리는가**를 실측한다.

## 무엇을 비교하는가

`app/db.py`가 만드는 합성 검사 DB(600행, 시드 42)를 SQLite와 PostgreSQL(WSL2 로컬,
`postgresql-16`, apt 설치 — 서버·클라우드 계정 불필요) 양쪽에 동일하게 적재하고:

  1. **이식 가능 질의 15종** — Analytics 에이전트가 실제로 만들 법한 SELECT(집계·필터·정렬).
     두 백엔드에서 결과 행 집합이 완전히 일치하는지 확인.
  2. **SQLite 전용 함수를 쓴 질의 1종** — `strftime('%m', ts)`(SQLite 내장). Postgres에는
     이 함수가 없다. NL2SQL이 이런 SQL을 생성하면 실행 전에 잡혀야 한다 — `sqlutils.dry_run`과
     같은 목적(EXPLAIN으로 컴파일 검증, 미실행)을 Postgres의 EXPLAIN으로도 재현해 실제로
     걸리는지 확인한다.
  3. **왕복 지연** — 같은 질의를 5회씩 반복해 SQLite(파일)와 Postgres(TCP 소켓) 실행 시간을
     비교한다(당연히 프로세스 간 통신이 있는 Postgres가 더 걸릴 것으로 예상 — 그 예상이 맞는지도
     실측으로 확인한다).

## 실행

    python tools/postgres_parity.py

전제: WSL2에 `sudo service postgresql start`로 PostgreSQL이 떠 있고, `inspection_copilot`
DB가 있으며 postgres 유저 비밀번호를 환경변수 `PG_PASSWORD`로 넘긴다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

OUT = ROOT / "tools" / "postgres_parity_result.json"

PG_DSN = dict(host="localhost", port=5432, dbname="inspection_copilot", user="postgres",
              password=os.environ.get("PG_PASSWORD", ""))  # 로컬 테스트 DB 비밀번호는 환경변수로
N_LATENCY_REPEATS = 5

# Analytics 에이전트가 실제로 만들 법한 이식 가능 질의(스키마 그라운딩의 예시 질문 계열).
PORTABLE_QUERIES = [
    "SELECT defect_class, COUNT(*) AS n FROM inspections WHERE line = 'L2' GROUP BY defect_class ORDER BY n DESC",
    "SELECT COUNT(*) FROM inspections WHERE severity = 'high'",
    "SELECT product, COUNT(*) AS n FROM inspections WHERE defect_class != 'none' GROUP BY product ORDER BY n DESC",
    "SELECT line, ROUND(AVG(CASE WHEN defect_class != 'none' THEN 1.0 ELSE 0.0 END), 3) AS defect_rate FROM inspections GROUP BY line ORDER BY defect_rate DESC",
    "SELECT * FROM inspections WHERE ts >= '2026-06-01' AND ts <= '2026-06-30' ORDER BY id LIMIT 20",
    "SELECT severity, COUNT(*) AS n FROM inspections WHERE severity IS NOT NULL GROUP BY severity ORDER BY n DESC",
    "SELECT COUNT(*) FROM inspections WHERE reviewed = 0 AND severity = 'high'",
    "SELECT product, line, COUNT(*) AS n FROM inspections GROUP BY product, line ORDER BY n DESC LIMIT 10",
    "SELECT AVG(confidence) AS avg_conf FROM inspections WHERE defect_class = 'none'",
    "SELECT defect_class, MIN(confidence) AS min_c, MAX(confidence) AS max_c FROM inspections WHERE defect_class != 'none' GROUP BY defect_class",
    "SELECT ts, COUNT(*) AS n FROM inspections GROUP BY ts ORDER BY n DESC LIMIT 5",
    "SELECT COUNT(DISTINCT product) FROM inspections",
    "SELECT line FROM inspections WHERE defect_class != 'none' GROUP BY line HAVING COUNT(*) > 50",
    "SELECT * FROM inspections WHERE confidence < 0.6 ORDER BY confidence ASC LIMIT 10",
    "SELECT product, defect_class, COUNT(*) AS n FROM inspections WHERE line = 'L3' GROUP BY product, defect_class ORDER BY n DESC LIMIT 10",
]

# SQLite 내장 함수(strftime) — Postgres엔 없다. NL2SQL이 흔히 "이번 달" 질문에 이런 SQL을 낼 수 있다.
SQLITE_ONLY_QUERY = "SELECT strftime('%m', ts) AS month, COUNT(*) AS n FROM inspections GROUP BY month ORDER BY month"


def build_sqlite(path: str) -> None:
    db.rebuild_db(path, n_rows=600, seed=42)


def build_postgres(rows: list[tuple]) -> None:
    import psycopg2

    conn = psycopg2.connect(**PG_DSN)
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS inspections")
        cur.execute(
            """
            CREATE TABLE inspections (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                product TEXT NOT NULL,
                line TEXT NOT NULL,
                defect_class TEXT NOT NULL,
                severity TEXT,
                confidence REAL NOT NULL,
                reviewed INTEGER NOT NULL
            )
            """
        )
        cur.executemany(
            "INSERT INTO inspections VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows
        )
        conn.commit()
    finally:
        conn.close()


def fetch_rows_sqlite_source(path: str) -> list[tuple]:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT * FROM inspections ORDER BY id").fetchall()
    finally:
        conn.close()


def run_sqlite(path: str, sql: str) -> tuple[list[tuple], float]:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        times = []
        rows = None
        for _ in range(N_LATENCY_REPEATS):
            t0 = time.perf_counter()
            rows = conn.execute(sql).fetchall()
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        return rows, times[len(times) // 2]
    finally:
        conn.close()


def run_postgres(sql: str) -> tuple[list[tuple], float]:
    import psycopg2

    conn = psycopg2.connect(**PG_DSN)
    try:
        cur = conn.cursor()
        times = []
        rows = None
        for _ in range(N_LATENCY_REPEATS):
            t0 = time.perf_counter()
            cur.execute(sql)
            rows = cur.fetchall()
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        return rows, times[len(times) // 2]
    finally:
        conn.close()


def dry_run_sqlite(path: str, sql: str) -> tuple[bool, str]:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        conn.execute("EXPLAIN " + sql)
        return True, ""
    except sqlite3.Error as e:
        return False, str(e)
    finally:
        conn.close()


def dry_run_postgres(sql: str) -> tuple[bool, str]:
    import psycopg2

    conn = psycopg2.connect(**PG_DSN)
    try:
        cur = conn.cursor()
        cur.execute("EXPLAIN " + sql)
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def main() -> None:
    sqlite_path = str(ROOT / "data" / "inspection_pg_parity_source.db")

    print("[1/4] SQLite 소스 DB 구축 (기존 app/db.py 로직 재사용, 시드 42)")
    build_sqlite(sqlite_path)
    rows = fetch_rows_sqlite_source(sqlite_path)
    print(f"  {len(rows)}행")

    print("[2/4] 같은 행을 PostgreSQL(WSL2 로컬)에 적재")
    build_postgres(rows)

    print("[3/4] 이식 가능 질의 15종 — 결과 일치 + 지연 비교")
    mismatches = []
    lat_sqlite, lat_pg = [], []
    for i, q in enumerate(PORTABLE_QUERIES):
        r_sqlite, ms_sqlite = run_sqlite(sqlite_path, q)
        r_pg, ms_pg = run_postgres(q)

        def _norm(v):
            # psycopg2는 ROUND()/NUMERIC을 Decimal로, sqlite3는 REAL을 float으로 돌려준다.
            # Decimal('0.495') == 0.495 는 False다(0.495는 이진 부동소수로 정확히 안 떨어짐) —
            # 드라이버가 다른 두 백엔드의 결과를 비교하려면 먼저 같은 타입으로 맞춰야 한다.
            from decimal import Decimal
            if isinstance(v, Decimal):
                v = float(v)
            return round(v, 6) if isinstance(v, float) else v

        set_sqlite = set(tuple(_norm(v) for v in r) for r in r_sqlite)
        set_pg = set(tuple(_norm(v) for v in r) for r in r_pg)
        match = set_sqlite == set_pg
        if not match:
            mismatches.append({
                "query": q, "sqlite_rows": len(r_sqlite), "pg_rows": len(r_pg),
                "sqlite_only": list(set_sqlite - set_pg), "pg_only": list(set_pg - set_sqlite),
            })
        lat_sqlite.append(ms_sqlite)
        lat_pg.append(ms_pg)
        print(f"  [{i+1}/{len(PORTABLE_QUERIES)}] {'일치' if match else '!! 불일치'} "
              f"(sqlite {ms_sqlite:.2f}ms · pg {ms_pg:.2f}ms)")

    print("[4/4] SQLite 전용 함수(strftime) 질의 — dry-run 가드가 Postgres에서도 걸리는지")
    ok_sqlite, err_sqlite = dry_run_sqlite(sqlite_path, SQLITE_ONLY_QUERY)
    ok_pg, err_pg = dry_run_postgres(SQLITE_ONLY_QUERY)
    print(f"  SQLite dry-run: {'통과' if ok_sqlite else f'실패({err_sqlite})'}")
    print(f"  Postgres dry-run: {'통과' if ok_pg else f'실패({err_pg})'}")

    def summarize(xs):
        xs = sorted(xs)
        n = len(xs)
        return {"mean": sum(xs) / n, "median": xs[n // 2]}

    report = {
        "n_rows": len(rows),
        "n_portable_queries": len(PORTABLE_QUERIES),
        "n_mismatches": len(mismatches),
        "mismatches": mismatches,
        "latency_ms": {"sqlite": summarize(lat_sqlite), "postgres": summarize(lat_pg)},
        "sqlite_only_function_probe": {
            "query": SQLITE_ONLY_QUERY,
            "sqlite_dry_run_ok": ok_sqlite,
            "postgres_dry_run_ok": ok_pg,
            "postgres_error": err_pg,
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
