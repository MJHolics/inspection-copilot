"""Report 에이전트 테스트 — context 종합·needs_human 전파·PDF 폴백. 오프라인."""
from __future__ import annotations

import pytest

from app.agents import AgentRequest
from app.agents.report import ReportAgent


def _ctx():
    return {
        "vision": {"summary": "결함 1건", "confidence": 0.88, "needs_human": False, "ok": True, "data": {}},
        "analytics": {"summary": "10건", "confidence": 0.7, "needs_human": False, "ok": True, "data": {}},
    }


def test_synthesizes_markdown():
    res = ReportAgent().run(AgentRequest(text="검사 보고서 만들어줘", context=_ctx()))
    assert res.ok
    assert res.data["sections"] == ["vision", "analytics"]
    assert "검사 종합 리포트" in res.data["markdown"]
    assert res.data["pdf_path"] is None  # 경로 미지정 → markdown만


def test_excludes_self_from_records():
    ctx = _ctx()
    ctx["report"] = {"summary": "self", "confidence": 1.0, "needs_human": False, "ok": True, "data": {}}
    res = ReportAgent().run(AgentRequest(text="q", context=ctx))
    assert "report" not in res.data["sections"]


def test_needs_human_propagates():
    ctx = {"knowledge": {"summary": "근거 부족", "confidence": 0.1, "needs_human": True, "ok": True, "data": {}}}
    res = ReportAgent().run(AgentRequest(text="q", context=ctx))
    assert res.needs_human is True
    assert "사람 검토" in res.summary


def test_pdf_generation_when_reportlab_present(tmp_path):
    pytest.importorskip("reportlab")
    path = str(tmp_path / "report.pdf")
    res = ReportAgent(pdf_path=path).run(AgentRequest(text="PDF 보고서", context=_ctx()))
    assert res.data["pdf_path"] == path
    import os
    assert os.path.exists(path) and os.path.getsize(path) > 0


def test_pdf_failure_falls_back_to_markdown(monkeypatch):
    # reportlab import 실패를 흉내 → markdown만, 에이전트는 ok 유지.
    # report 모듈이 to_pdf를 이름으로 import했으므로 그 네임스페이스를 패치한다.
    import app.agents.report as report_mod

    def boom(report, path):
        raise ImportError("no reportlab")

    monkeypatch.setattr(report_mod, "to_pdf", boom)
    res = ReportAgent(pdf_path="x.pdf").run(AgentRequest(text="q", context=_ctx()))
    assert res.ok and res.data["pdf_path"] is None
    assert "markdown만" in res.summary
