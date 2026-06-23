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


def build_routing_system(agents: dict[str, BaseAgent]) -> str:
    """라우팅용 system 프롬프트 — 에이전트 카탈로그 + 출력 규약(JSON)."""
    catalog = "\n".join(f"- {name}: {a.description}" for name, a in agents.items())
    return (
        "너는 검사 코파일럿의 라우터다. 사용자 요청을 보고 아래 에이전트 중 **필요한 것만** "
        "실행 순서대로 고른다. 불필요한 에이전트는 넣지 마라. 여러 에이전트 결과를 종합해야 하면 "
        "마지막에 report를 넣어라. 설명 없이 **JSON만** 출력한다: "
        '{"steps": ["에이전트명", ...], "reason": "한 줄 근거"}\n\n'
        f"에이전트:\n{catalog}"
    )


def build_routing_user(req: AgentRequest) -> str:
    img = "\n[이미지가 첨부됨 — 시각 검사 필요]" if req.image_path else ""
    return f"요청: {req.text}{img}"


def parse_plan(text: str, agents: dict[str, BaseAgent]) -> tuple[list[str], str]:
    """LLM 출력에서 JSON 계획을 파싱 → (알려진 에이전트로 필터된 steps, reason). 순수."""
    import json
    import re

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("JSON 계획을 찾지 못함")
    data = json.loads(m.group(0))
    steps = [s for s in data.get("steps", []) if s in agents]
    return steps, str(data.get("reason", ""))


class LLMRouter:
    """실 LLM tool-calling 라우터 — 에이전트 카탈로그를 주고 모델이 경로를 고르게 한다.

    `complete(system, user) -> str`(예: app.llm.LLM().complete)를 주입받아 JSON 계획을 파싱한다.
    이미지가 있으면 vision을 강제하고, 다중 에이전트면 report 종합을 보장한다. 어떤 실패(키 없음·
    JSON 파싱 실패·빈 계획)든 RuleRouter로 안전 폴백한다 — 라우팅이 죽지 않는다.
    """

    name = "llm"

    def __init__(self, complete=None, fallback: RuleRouter | None = None) -> None:
        self.complete = complete
        self.fallback = fallback or RuleRouter()

    def _fallback(self, req: AgentRequest, agents: dict[str, BaseAgent], why: str) -> RoutePlan:
        fb = self.fallback.plan(req, agents)
        fb.reason = f"{why} → 규칙 폴백 · {fb.reason}"
        fb.router = "llm->rule"
        return fb

    def plan(self, req: AgentRequest, agents: dict[str, BaseAgent]) -> RoutePlan:
        if self.complete is None:
            return self._fallback(req, agents, "LLM 미주입")
        try:
            raw = self.complete(build_routing_system(agents), build_routing_user(req))
            steps, reason = parse_plan(raw, agents)
        except Exception as e:
            return self._fallback(req, agents, f"LLM 라우팅 실패({type(e).__name__})")

        names = set(steps)
        if req.image_path:
            names.add("vision")          # 이미지가 있으면 시각 검사는 항상
        if not names:
            return self._fallback(req, agents, "LLM이 유효 에이전트를 고르지 못함")
        if len(names - {"report"}) >= 2:
            names.add("report")          # 다중 → 종합 리포트 보장
        return RoutePlan(steps=_order(names), reason=f"LLM: {reason}", router=self.name)


def default_llm_router() -> "LLMRouter | None":
    """키가 있으면 실 LLM 라우터를 만든다(app.llm). 키/SDK 없으면 None(→ 규칙 라우터 사용)."""
    try:
        from .llm import LLM

        client = LLM()  # 키 없으면 여기서 예외
        return LLMRouter(complete=lambda s, u: client.complete(s, u, temperature=0.0))
    except Exception:
        return None
