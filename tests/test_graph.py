"""LangGraph 결선 테스트 — langgraph 설치 시에만 실행(미설치면 skip). 동일 라우터·에이전트 검증."""
from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from app.graph import run_graph  # noqa: E402


def test_graph_runs_same_route():
    state = run_graph("이번 달 불량 통계로 보고서 만들어줘")
    assert "analytics" in state["route"]
    assert state["route"][-1] == "report"
    # cursor가 경로 끝까지 진행했는지(모든 단계 실행).
    assert state["cursor"] == len(state["route"])
    assert len(state["results"]) == len(state["route"])
