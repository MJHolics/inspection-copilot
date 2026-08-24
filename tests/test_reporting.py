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


# --- 2026-08-18 회귀 방지: 실패한 단계가 있으면 "신뢰 가능"이라고 말하지 않는다 ---------
# 이전에는 needs_human 플래그만 OR 했다. 실패했지만 플래그를 세우지 않는 경로(vision의
# no_image)가 실재해서, 같은 리포트가 findings에서는 "실패/미완료 — 결과를 신뢰할 수 없음"이라
# 하고 recommendation에서는 "모든 단계가 임계 이상으로 완료되었다"고 하는 자기모순이 났다.

def test_failed_step_without_human_flag_still_blocks_auto_verdict():
    recs = {
        "vision": {"summary": "이미지가 없어 검사 불가", "confidence": 1.0,
                   "needs_human": False, "ok": False},
        "knowledge": {"summary": "근거 확보", "confidence": 0.91,
                      "needs_human": False, "ok": True},
    }
    r = build_report("질문", recs)
    assert r.needs_human is True
    assert "신뢰 가능" not in r.recommendation
    assert "보류" in r.recommendation


def test_failed_step_does_not_inflate_overall_confidence():
    """실패한 단계의 confidence가 1.0로 남아 있어도 종합신뢰도를 끌어올리면 안 된다."""
    recs = {
        "vision": {"summary": "실패", "confidence": 1.0, "needs_human": False, "ok": False},
        "knowledge": {"summary": "ok", "confidence": 0.91, "needs_human": False, "ok": True},
    }
    assert build_report("질문", recs).overall_confidence == 0.0


def test_findings_and_recommendation_do_not_contradict():
    """findings가 실패를 말하는데 recommendation이 신뢰 가능이라 말하는 조합은 없어야 한다."""
    for ok_flags in [(True, True), (True, False), (False, True), (False, False)]:
        recs = {
            f"a{i}": {"summary": "", "confidence": 0.9, "needs_human": False, "ok": ok}
            for i, ok in enumerate(ok_flags)
        }
        r = build_report("질문", recs)
        says_failed = any("실패/미완료" in f for f in r.findings)
        says_trustworthy = r.recommendation.startswith("자동 판정 신뢰 가능")
        assert not (says_failed and says_trustworthy)
