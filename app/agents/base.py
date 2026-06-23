"""에이전트 인터페이스 계약 — 모든 서브에이전트가 따르는 단일 형태.

supervisor는 이 계약만 알면 어떤 서브에이전트든 동일하게 호출·종합·라우팅할 수 있다.
각 에이전트는 `description`/`keywords`를 노출해 라우터(규칙 또는 LLM tool-calling)가
무엇을 부를지 판단하는 근거로 쓴다. 반환 타입(`AgentResult`)은 근거(evidence)·신뢰도·
사람검토 플래그를 강제해, "동작"이 아니라 "검증 가능한" 응답을 구조적으로 보장한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentRequest:
    """서브에이전트에 전달되는 단위 요청.

    `context`는 앞선 에이전트가 남긴 산출물 누적분(에이전트명 → data)이라, 뒤 에이전트가
    참조할 수 있다(예: Report가 Vision/Analytics 결과를 모아 리포트화).
    """

    text: str
    image_path: str | None = None
    context: dict = field(default_factory=dict)


@dataclass
class Evidence:
    """답을 뒷받침하는 근거 한 조각. source는 추적 가능한 출처여야 한다."""

    source: str            # 예: "NEU-DB", "SOP-7.3", "image:scratch_01.jpg"
    detail: str
    score: float | None = None  # 관련도/신뢰도(있으면)


@dataclass
class AgentResult:
    """모든 서브에이전트의 표준 반환형.

    - confidence: 0~1. 낮으면 supervisor가 사람검토로 라우팅할 수 있다.
    - needs_human: 가드레일/trust 층이 "모름"이라 판단하면 True(멈춤 신호).
    - data: 다운스트림 에이전트가 쓸 구조화 페이로드.
    """

    agent: str
    ok: bool
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 1.0
    needs_human: bool = False
    data: dict = field(default_factory=dict)
    error: str | None = None


class BaseAgent:
    """서브에이전트 베이스. 하위 클래스는 `name`/`description`/`run`을 채운다.

    `description`은 라우터(특히 P2의 LLM tool-calling)가 읽는 도구 설명이고,
    `keywords`는 P1 규칙 라우터가 의도를 매칭하는 데 쓰는 한국어/영어 트리거다.
    """

    name: str = "base"
    description: str = ""
    keywords: tuple[str, ...] = ()

    def run(self, req: AgentRequest) -> AgentResult:  # pragma: no cover - 추상
        raise NotImplementedError

    # 라우터가 쓰는 도구 스키마(P2 LLM tool-calling에서 그대로 함수 선언으로 변환).
    def tool_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "사용자 요청 원문"},
                },
                "required": ["text"],
            },
        }
