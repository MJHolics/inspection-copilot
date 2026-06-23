"""합성 검사 DB 테스트 — 결정적 생성·스키마 검증. 오프라인."""
from __future__ import annotations

from app import config, db


def test_rebuild_is_deterministic(tmp_path):
    p1 = str(tmp_path / "a.db")
    p2 = str(tmp_path / "b.db")
    db.rebuild_db(p1, n_rows=200, seed=7)
    db.rebuild_db(p2, n_rows=200, seed=7)
    c1, c2 = db.connect(p1), db.connect(p2)
    try:
        r1 = c1.execute("SELECT id, defect_class, line FROM inspections ORDER BY id").fetchall()
        r2 = c2.execute("SELECT id, defect_class, line FROM inspections ORDER BY id").fetchall()
        assert [tuple(r) for r in r1] == [tuple(r) for r in r2]
        assert len(r1) == 200
    finally:
        c1.close()
        c2.close()


def test_schema_and_values(tmp_path):
    p = str(tmp_path / "c.db")
    db.rebuild_db(p, n_rows=300, seed=1)
    conn = db.connect(p)
    try:
        # 양품은 defect_class='none', 그 외는 6종 중 하나.
        classes = {r[0] for r in conn.execute("SELECT DISTINCT defect_class FROM inspections")}
        assert "none" in classes
        assert classes - {"none"} <= set(config.DEFECT_CLASSES)
        # confidence 범위.
        mn, mx = conn.execute("SELECT min(confidence), max(confidence) FROM inspections").fetchone()
        assert 0.0 <= mn <= mx <= 1.0
    finally:
        conn.close()


def test_schema_card_mentions_columns():
    card = db.schema_card()
    assert "inspections" in card and "defect_class" in card and "SELECT 전용" in card
