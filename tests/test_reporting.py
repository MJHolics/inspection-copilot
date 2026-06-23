"""리포트 빌더 테스트 — 종합 신뢰도·사람검토 전파·마크다운. 순수/오프라인."""
from __future__ import annotations

from app.reporting import build_report, to_markdown


def _records():
    return {
        "vision": {"summary": "결함 감지", "confidence": 0.9, "needs_human": False, "ok": True},
        "analytics": {"summary": "통계 산출", "confidence": 0.6, "needs_human": False, "ok": True},
    }


def test_overall_confidence_is_min():
    r = build_report("질문", _records())
    assert r.overall_confidence == 0.6  # 가장 약한 고리
    assert not r.needs_human
    assert "신뢰 가능" in r.recommendation


def test_needs_human_propagates_or():
    recs = _records()
    recs["knowledge"] = {"summary": "근거 부족", "confidence": 0.1, "needs_human": True, "ok": True}
    r = build_report("질문", recs)
    assert r.needs_human is True
    assert any("사람 검토" in f for f in r.findings)
    assert "보류" in r.recommendation


def test_failed_step_flagged():
    recs = {"analytics": {"summary": "실패", "confidence": 0.0, "needs_human": True, "ok": False}}
    r = build_report("q", recs)
    assert any("신뢰할 수 없음" in f for f in r.findings)


def test_markdown_has_sections_and_reco():
    md = to_markdown(build_report("불량 보고서", _records()))
    assert "검사 종합 리포트" in md
    assert "단계별 결과" in md and "권고" in md
    assert "vision" in md and "analytics" in md


def test_empty_records():
    r = build_report("q", {})
    assert r.sections == []
    assert "종합할 입력이 없습니다" in r.recommendation
