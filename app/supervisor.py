"""Supervisor — 요청을 라우팅하고 서브에이전트를 실행해 종합하는 오케스트레이터.

흐름: 라우터가 계획(어떤 에이전트를 어떤 순서로) → 순서대로 실행하며 context 누적 →
각 단계를 트레이싱 → 결과를 종합 답으로 합치고, 어느 단계든 사람검토를 요청하면 전체를
needs_human으로 올린다("모를 때 멈춤" 가드레일). LangGraph 결선은 `app/graph.py` 참고
(같은 라우터+에이전트를 StateGraph로 실행). 핵심 로직은 여기에 순수하게 두어 테스트 가능.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .agents import AgentRequest, AgentResult, BaseAgent, default_registry
from .router import RoutePlan, RuleRouter
from .trace import RequestTrace, StepRecord, Tracer, now_iso


@dataclass
class SupervisorResult:
    """최종 응답 + 추적 가능한 메타(계획·단계별 결과·트레이스)."""

    answer: str
    plan: RoutePlan
    results: list[AgentResult] = field(default_factory=list)
    needs_human: bool = False
    ok: bool = True
    trace: RequestTrace | None = None


class Supervisor:
    def __init__(self, agents=None, router=None, tracer: Tracer | None = None) -> None:
        self.agents: dict[str, BaseAgent] = agents or default_registry()
        self.router = router or RuleRouter()
        self.tracer = tracer if tracer is not None else Tracer()

    def handle(self, text: str, image_path: str | None = None) -> SupervisorResult:
        req = AgentRequest(text=text, image_path=image_path, context={})
        plan = self.router.plan(req, self.agents)

        steps: list[StepRecord] = []
        results: list[AgentResult] = []
        ctx: dict = {}
        t_start = time.perf_counter()

        for name in plan.steps:
            agent = self.agents[name]
            t0 = time.perf_counter()
            res = agent.run(AgentRequest(text=text, image_path=image_path, context=ctx))
            latency = int((time.perf_counter() - t0) * 1000)
            results.append(res)
            # 다운스트림(특히 report)이 참조할 구조화 레코드. data만이 아니라 요약·신뢰도·플래그까지.
            ctx[name] = {
                "summary": res.summary,
                "confidence": res.confidence,
                "needs_human": res.needs_human,
                "ok": res.ok,
                "data": res.data,
            }
            steps.append(
                StepRecord(
                    agent=name,
                    ok=res.ok,
                    latency_ms=latency,
                    confidence=res.confidence,
                    needs_human=res.needs_human,
                    error=res.error,
                )
            )

        total_latency = int((time.perf_counter() - t_start) * 1000)
        needs_human = any(r.needs_human for r in results)
        ok = all(r.ok for r in results)
        answer = self._synthesize(plan, results, needs_human)

        trace = RequestTrace(
            ts=now_iso(),
            request=text,
            router=plan.router,
            route=plan.steps,
            steps=steps,
            total_latency_ms=total_latency,
            ok=ok,
            needs_human=needs_human,
        )
        if self.tracer is not None:
            self.tracer.emit(trace)

        return SupervisorResult(
            answer=answer,
            plan=plan,
            results=results,
            needs_human=needs_human,
            ok=ok,
            trace=trace,
        )

    @staticmethod
    def _synthesize(plan: RoutePlan, results: list[AgentResult], needs_human: bool) -> str:
        """단계별 결과를 사람이 읽는 종합 답으로 합친다(근거·신뢰도 동반)."""
        lines = [f"[라우팅: {' → '.join(plan.steps)} · {plan.reason}]", ""]
        for res in results:
            tag = "✓" if res.ok else "✗"
            conf = f" (신뢰도 {res.confidence:.2f})" if res.confidence else ""
            lines.append(f"{tag} {res.agent}{conf}: {res.summary}")
            for ev in res.evidence:
                lines.append(f"    근거: {ev.source} — {ev.detail}")
        if needs_human:
            lines += ["", "⚠ 신뢰도 부족 — 사람 검토가 필요한 항목이 있습니다."]
        return "\n".join(lines)
