"""서브에이전트 레지스트리 — 이름 → 인스턴스. supervisor/router가 단일 진입점으로 쓴다."""
from __future__ import annotations

from .analytics import AnalyticsAgent
from .base import AgentRequest, AgentResult, BaseAgent, Evidence
from .knowledge import KnowledgeAgent
from .report import ReportAgent
from .vision import VisionAgent

# 라우팅 실행 순서의 기준(서브에이전트 → 종합). report는 항상 마지막에 오도록 라우터가 보장.
AGENT_ORDER: tuple[str, ...] = ("vision", "analytics", "knowledge", "report")


def default_registry() -> dict[str, BaseAgent]:
    """기본 4개 에이전트 레지스트리(이름 → 인스턴스)."""
    agents: list[BaseAgent] = [VisionAgent(), AnalyticsAgent(), KnowledgeAgent(), ReportAgent()]
    return {a.name: a for a in agents}


__all__ = [
    "AgentRequest",
    "AgentResult",
    "BaseAgent",
    "Evidence",
    "VisionAgent",
    "AnalyticsAgent",
    "KnowledgeAgent",
    "ReportAgent",
    "AGENT_ORDER",
    "default_registry",
]
