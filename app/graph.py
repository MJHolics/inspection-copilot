"""LangGraph 결선 — supervisor를 StateGraph로 실행하는 동적 라우팅 그래프.

`app/supervisor.py`의 순수 오케스트레이터와 동일한 라우터·에이전트를 쓰되, 실행을 LangGraph
StateGraph로 표현한다: supervisor 노드가 다음 에이전트를 고르고(조건부 엣지), 해당 에이전트
노드를 돈 뒤 다시 supervisor로 돌아와 남은 단계가 없으면 END로 간다. "고정 체인"이 아니라
요청별로 경로가 달라지는 tool-calling 스타일 라우팅을 그래프로 시각화·확장하기 위한 골격.

LangGraph 의존성은 선택. 미설치 시 `build_graph()`는 ImportError를 그대로 올린다(테스트는 skip).
실 LLM tool-calling 라우터(LLMRouter) 결선과 노드별 트레이싱 강화는 P2.
"""
from __future__ import annotations

from typing import Any

from .agents import AgentRequest, default_registry
from .router import RuleRouter


def build_graph(agents: dict | None = None, router: Any | None = None):
    """LangGraph StateGraph를 만들어 compile한다(langgraph 필요)."""
    from langgraph.graph import END, START, StateGraph  # 지연 import(선택 의존성)

    agents = agents or default_registry()
    router = router or RuleRouter()

    def supervisor_node(state: dict) -> dict:
        # 첫 진입: 라우터로 계획 수립. 이후: 다음 단계로 포인터만 전진.
        if "route" not in state:
            req = AgentRequest(text=state["text"], image_path=state.get("image_path"))
            plan = router.plan(req, agents)
            state["route"] = plan.steps
            state["reason"] = plan.reason
            state["router"] = plan.router
            state["cursor"] = 0
            state.setdefault("results", [])
            state.setdefault("ctx", {})
        return state

    def make_agent_node(name: str):
        def node(state: dict) -> dict:
            agent = agents[name]
            res = agent.run(
                AgentRequest(text=state["text"], image_path=state.get("image_path"), context=state["ctx"])
            )
            state["results"].append(res)
            state["ctx"][name] = res.data
            state["cursor"] += 1
            return state

        return node

    def route_next(state: dict) -> str:
        route = state["route"]
        cursor = state["cursor"]
        if cursor >= len(route):
            return END
        return route[cursor]

    g = StateGraph(dict)
    g.add_node("supervisor", supervisor_node)
    for name in agents:
        g.add_node(name, make_agent_node(name))
        g.add_edge(name, "supervisor")  # 각 에이전트 후 supervisor로 복귀
    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_next,
        {**{name: name for name in agents}, END: END},
    )
    return g.compile()


def run_graph(text: str, image_path: str | None = None) -> dict:
    """그래프를 한 번 실행해 최종 상태(results·route 포함)를 반환."""
    graph = build_graph()
    return graph.invoke({"text": text, "image_path": image_path})
