"""FastAPI 서버 스모크 — TestClient로 엔드포인트 검증. fastapi 없으면 skip. 오프라인."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient 의존

from fastapi.testclient import TestClient  # noqa: E402

from app.server import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_inspect_knowledge():
    r = client.post("/inspect", json={"question": "스크래치 결함 처리 절차 알려줘"})
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == ["knowledge"]
    assert body["agents"][0]["agent"] == "knowledge"
    assert not body["needs_human"]


def test_inspect_multi_has_report_markdown():
    r = client.post("/inspect", json={"question": "스크래치 처리 절차 정리해서 보고서로 줘"})
    body = r.json()
    assert "report" in body["route"]
    assert body["report_markdown"] and "검사 종합 리포트" in body["report_markdown"]


def test_eval_endpoint():
    r = client.get("/eval")
    assert r.status_code == 200
    s = r.json()
    assert s["routing_exact_acc"] == 1.0 and s["e2e_success_rate"] == 1.0
