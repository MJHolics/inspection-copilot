"""SQL 가드레일·dry-run 테스트 — 순수/SQLite. 오프라인."""
from __future__ import annotations

from app import db
from app.sqlutils import dry_run, extract_sql, is_safe_select


def test_extract_strips_fences():
    assert extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("SELECT 1") == "SELECT 1"


def test_safe_select_ok():
    ok, _ = is_safe_select("SELECT count(*) FROM inspections")
    assert ok


def test_rejects_dml():
    for bad in ["DELETE FROM inspections", "DROP TABLE inspections",
                "UPDATE inspections SET reviewed=1", "INSERT INTO inspections VALUES (1)"]:
        ok, why = is_safe_select(bad)
        assert not ok, bad


def test_rejects_multi_statement():
    ok, _ = is_safe_select("SELECT 1; SELECT 2")
    assert not ok


def test_allows_with_cte():
    ok, _ = is_safe_select("WITH t AS (SELECT 1 AS x) SELECT x FROM t")
    assert ok


def test_dry_run_catches_bad_column(tmp_path):
    p = str(tmp_path / "d.db")
    db.rebuild_db(p, n_rows=50, seed=1)
    conn = db.connect(p)
    try:
        ok, _ = dry_run(conn, "SELECT count(*) FROM inspections")
        assert ok
        bad, err = dry_run(conn, "SELECT nonexistent_col FROM inspections")
        assert not bad and "nonexistent_col" in err
    finally:
        conn.close()
