"""동적 라우터 — 요청마다 어떤 서브에이전트를 어떤 순서로 부를지 정한다.

고정 3단계 체인(기존 `vision-inspection-agent`의 한계)과 달리, 요청 내용에 따라 호출 집합과
순서가 달라진다. 두 구현을 제공한다:

  • RuleRouter — 의도 키워드 + 이미지 유무로 결정(결정적·오프라인·단위테스트 가능). P1 기본.
  • LLMRouter  — 서브에이전트 description을 도구로 노출하고 LLM tool-calling으로 계획을 받는다.
                 P2에서 실 LLM과 결선. 키/네트워크 없으면 RuleRouter로 폴백.

둘 다 `plan(req, agents) -> RoutePlan`을 구현해 supervisor가 동일하게 쓴다.
실행 순서는 항상 AGENT_ORDER를 따르되 report는 마지막(종합)으로 강제한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .agents import AGENT_ORDER, AgentRequest, BaseAgent


@dataclass
class RoutePlan:
    """라우팅 결정. steps는 실행 순서대로의 에이전트명, reason은 설명, router는 어느 라우터가 냈는지."""

    steps: list[str]
    reason: str
    router: str = "rule"
    scores: dict[str, int] = field(default_factory=dict)


def _order(names: set[str]) -> list[str]:
    """AGENT_ORDER 기준 정렬 + report는 항상 마지막."""
    ordered = [n for n in AGENT_ORDER if n in names and n != "report"]
    if "report" in names:
        ordered.append("report")
    return ordered


class RuleRouter:
    """키워드·이미지 유무 기반 결정적 라우터(P1 기본).

    각 에이전트의 `keywords`를 요청 텍스트에 매칭해 점수를 매기고, 점수>0인 에이전트를 고른다.
    이미지가 있으면 vision은 무조건 포함. 아무것도 안 걸리면 knowledge로 폴백(일반 Q&A 그라운딩).
    선택된 실질 에이전트가 2개 이상이거나 명시적 리포트 요청이면 report를 종합 단계로 덧붙인다.
    """

    name = "rule"

    def plan(self, req: AgentRequest, agents: dict[str, BaseAgent]) -> RoutePlan:
        text = (req.text or "").lower()
        scores: dict[str, int] = {}
        for name, agent in agents.items():
            hits = sum(1 for kw in agent.keywords if kw.lower() in text)
            if hits:
                scores[name] = hits

        chosen: set[str] = {n for n, s in scores.items() if s > 0}

        # Vision은 이미지가 있어야만 의미가 있다. 이미지 있으면 항상 포함, 없으면 제외
        # ('불량/결함' 같은 일반 단어는 텍스트 질문에도 흔히 나오므로 키워드만으론 호출 안 함).
        if req.image_path:
            chosen.add("vision")
            scores["vision"] = scores.get("vision", 0) + 1
        else:
            chosen.discard("vision")

        # report는 명시 요청이 아니면 일단 후보에서 빼고, 종합 필요 여부로 다시 판단.
        report_requested = "report" in chosen
        chosen.discard("report")

        if not chosen:
            chosen = {"knowledge"}
            reason = "매칭된 의도가 없어 일반 지식 그라운딩(knowledge)으로 폴백."
        else:
            reason = "의도 키워드/이미지 매칭: " + ", ".join(
                f"{n}({scores.get(n, 0)})" for n in _order(chosen)
            )

        # 종합 단계: 여러 에이전트가 관여하거나 사용자가 리포트를 명시하면 report 추가.
        if report_requested or len(chosen) >= 2:
            chosen.add("report")
            if report_requested:
                reason += " · 리포트 명시 요청"
            else:
                reason += " · 다중 에이전트 → 종합 리포트"

        return RoutePlan(steps=_order(chosen), reason=reason, router=self.name, scores=scores)


class LLMRouter:
    """LLM tool-calling 라우터(P2에서 실 LLM과 결선).

    서브에이전트 description을 도구 스키마로 노출하고, 모델이 호출할 도구(들)를 고르게 한다.
    P1에서는 `llm`(JSON 계획을 돌려주는 콜러블)을 주입받아 파싱만 한다. 주입 안 되면 RuleRouter로 폴백.
    """

    name = "llm"

    def __init__(self, llm=None, fallback: RuleRouter | None = None) -> None:
        self.llm = llm
        self.fallback = fallback or RuleRouter()

    def plan(self, req: AgentRequest, agents: dict[str, BaseAgent]) -> RoutePlan:
        if self.llm is None:
            fb = self.fallback.plan(req, agents)
            fb.reason = "LLM 미주입 → 규칙 라우터 폴백 · " + fb.reason
            fb.router = "llm->rule"
            return fb
        # TODO(P2): agents[*].tool_schema()를 함수 선언으로 LLM에 주고 tool_calls를 받아 steps 구성.
        raw = self.llm(req.text, [a.tool_schema() for a in agents.values()])
        steps = [s for s in raw.get("steps", []) if s in agents]
        if not steps:
            return self.fallback.plan(req, agents)
        names = set(steps)
        return RoutePlan(
            steps=_order(names),
            reason=raw.get("reason", "LLM tool-calling 라우팅"),
            router=self.name,
        )
