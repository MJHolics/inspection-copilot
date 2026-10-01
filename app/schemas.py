"""HTTP 응답 계약 — `/inspect`가 무엇을 돌려주는지 OpenAPI에 실제로 적히게 한다.

이전에는 엔드포인트가 `-> dict`라 OpenAPI 스키마가 `object` 하나였다. 그러면 프론트엔드(web/)가
타입을 생성해도 `unknown`밖에 못 얻는다. 응답 모양은 `service.result_to_dict`가 정하고, 이 모델은
그 모양을 선언한다(테스트가 둘이 어긋나지 않게 묶는다).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

AgentName = Literal["vision", "analytics", "knowledge", "report"]
RouterName = Literal["rule", "llm", "llm->rule"]


class Evidence(BaseModel):
    source: str
    detail: str
    score: float | None


class AgentOut(BaseModel):
    agent: AgentName
    ok: bool
    summary: str
    confidence: float
    needs_human: bool
    evidence: list[Evidence]


class InspectResponse(BaseModel):
    answer: str
    ok: bool
    needs_human: bool
    route: list[AgentName]
    router: RouterName
    reason: str
    grounding_retriever: str
    agents: list[AgentOut]
    report_markdown: str | None
    latency_ms: int | None


class InspectRequest(BaseModel):
    question: str
    image_path: str | None = None
