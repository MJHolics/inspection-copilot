"""내구 실행(durable execution) 층 — 체크포인트 · 단계 단위 재시도 · 멱등 부작용.

왜 필요했나: `Supervisor`는 단계 결과를 **메모리에만** 둔다. 프로세스가 죽으면 이미 끝난 단계까지
전부 잃고, 일시 고장(LLM 429·네트워크 순단)에 재시도가 없어 그대로 실패로 굳는다. 요청 전체를
다시 돌리는 순진한 재시도는 완주율은 올리지만 **되돌릴 수 없는 부작용(성적서 발행)을 중복 실행**한다.
`tools/bench_durability.py`가 그 셋을 같은 고장 스케줄로 짝지어 비교한다.

설계 결정 4가지:
  1. **계획은 재수립하지 않는다.** 재개할 때 라우터를 다시 부르면 단계 목록이 바뀌어 이미 끝난
     작업이 무효가 될 수 있다. 계획은 첫 실행 때 체크포인트에 박고 이후로는 그대로 재생한다.
  2. **재시도는 단계 단위로.** 성공한 단계는 다시 실행하지 않는다(부작용·비용 양쪽 이유).
  3. **나아지지 않는 실패는 재시도하지 않는다.** `no_image`·`unsafe_sql`처럼 입력·정책이 원인인
     실패는 몇 번을 불러도 같다. `NON_RETRYABLE`로 분류해 즉시 확정한다.
  4. **재시도를 소진한 단계는 사람검토로 올린다.** 각 에이전트가 `needs_human`을 세우는 규율에
     기대지 않는다 — 내구 층이 만들어내는 새 실패 유형("재시도 소진")은 에이전트가 모르기 때문이다.

멱등성: 각 단계는 `context["_idempotency_key"] = f"{run_id}:{step}"`를 받는다. 외부로 나가는
액션을 가진 에이전트는 이 키로 중복 발행을 막을 수 있고, 재개 시에는 애초에 그 단계를 다시
실행하지 않으므로 이중 방어가 된다.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .agents import AgentRequest, AgentResult, Evidence
from .guard import redact_secrets
from .router import RoutePlan
from .supervisor import Supervisor, SupervisorResult
from .trace import RequestTrace, StepRecord, now_iso

# 재시도해도 결과가 달라지지 않는 실패(입력·정책 원인). 여기 있으면 즉시 확정한다.
NON_RETRYABLE: frozenset = frozenset({
    "no_image",      # 이미지가 없다 — 다시 불러도 없다
    "unsafe_sql",    # 가드레일이 거부 — 정책 판단이라 재시도 대상이 아니다
    "no_llm",        # API 키 부재 — 환경 문제
})


# ---------------------------------------------------------------- 재시도 정책
@dataclass
class RetryPolicy:
    """지수 백오프 + 지터. `base_delay_s=0`이면 대기 없이(테스트·벤치용)."""

    max_attempts: int = 3
    base_delay_s: float = 0.2
    max_delay_s: float = 5.0
    jitter: float = 0.1
    seed: int | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def delay(self, attempt: int) -> float:
        """attempt는 1부터. 1회 실패 후 대기할 시간."""
        if self.base_delay_s <= 0:
            return 0.0
        d = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        return d * (1.0 + self._rng.uniform(-self.jitter, self.jitter))

    @staticmethod
    def is_retryable(error: str | None) -> bool:
        return error not in NON_RETRYABLE


# ---------------------------------------------------------------- 체크포인트
@dataclass
class RunState:
    """재개에 필요한 최소 상태. 계획과 이미 끝난 단계의 결과를 담는다."""

    run_id: str
    request: str
    image_path: str | None = None
    router: str = ""
    reason: str = ""
    plan_steps: list = field(default_factory=list)
    completed: dict = field(default_factory=dict)   # step -> AgentResult(dict)
    attempts: dict = field(default_factory=dict)    # step -> 소모한 시도 횟수
    effects: dict = field(default_factory=dict)     # idempotency_key -> ts (발행 기록)
    status: str = "running"                          # running | done | paused | failed
    updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        return cls(**d)


class FileCheckpointStore:
    """파일 한 개짜리 체크포인트 저장소. **원자적 교체**로 반쯤 쓰인 상태를 만들지 않는다.

    임시 파일에 다 쓰고 `os.replace`로 갈아끼운다. 쓰는 도중 프로세스가 죽어도 남는 것은
    직전의 온전한 상태이지, 잘린 JSON이 아니다(잘린 JSON은 재개 자체를 막는다).

    `fsync`는 **위협 모델에 따라 끈다.** 막으려는 것이 프로세스 사망(OOM 킬·컨테이너 교체·
    SIGKILL)이라면 `os.replace`의 원자성만으로 충분하다 — 페이지 캐시는 프로세스가 죽어도
    OS가 들고 있기 때문이다. `fsync`가 추가로 사는 것은 **머신 전원 손실·커널 패닉**뿐이고,
    그 대가가 이 워크로드에서 단계당 3.35ms 대 0.09ms다(`tools/bench_checkpoint_cost.py`).
    """

    def __init__(self, path, fsync: bool = True) -> None:
        self.path = Path(path)
        self.fsync = fsync
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RunState | None:
        if not self.path.exists():
            return None
        try:
            return RunState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            # 손상된 체크포인트는 없는 것으로 본다(처음부터 다시). 조용히 삼키지는 않는다.
            return None

    def save(self, state: RunState) -> None:
        state.updated = now_iso()
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, ensure_ascii=False)
                f.flush()
                if self.fsync:
                    os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class MemoryCheckpointStore:
    """테스트용 인메모리 저장소(같은 인터페이스). 프로세스 재시작 내성은 없다."""

    def __init__(self) -> None:
        self._state: RunState | None = None

    def load(self) -> RunState | None:
        return self._state

    def save(self, state: RunState) -> None:
        state.updated = now_iso()
        self._state = RunState.from_dict(json.loads(json.dumps(state.to_dict(), ensure_ascii=False)))


# ---------------------------------------------------------------- 직렬화
def _result_to_dict(res: AgentResult) -> dict:
    return asdict(res)


def _result_from_dict(d: dict) -> AgentResult:
    d = dict(d)
    ev = [Evidence(**e) for e in d.pop("evidence", [])]
    return AgentResult(evidence=ev, **d)


# ---------------------------------------------------------------- 내구 supervisor
class DurableSupervisor(Supervisor):
    """`Supervisor`와 같은 결과를 내되, 중간 상태를 남기고 단계 단위로 재시도한다.

    `store=None`이면 부모와 동일하게 동작한다(기존 경로 무영향 — 데모·서버는 그대로).
    """

    def __init__(self, agents=None, router=None, tracer=None,
                 store=None, retry: RetryPolicy | None = None,
                 budget_s: float | None = None) -> None:
        super().__init__(agents=agents, router=router, tracer=tracer)
        self.store = store
        self.retry = retry or RetryPolicy()
        self.budget_s = budget_s        # 이 시간을 넘기면 남은 단계를 남겨 두고 paused로 반환
        self.replayed_steps = 0         # 이미 성공한 단계를 다시 실행한 횟수(설계상 0이어야 한다)
        self.resumed_steps = 0          # 체크포인트 덕에 건너뛴 단계 수(아낀 작업)
        self.retried_steps = 0          # 재시도가 발생한 단계 수
        self.exhausted_steps = 0        # 재시도를 소진하고 실패로 확정된 단계 수

    # ------------------------------------------------------------ 공개 API
    def handle(self, text: str, image_path: str | None = None,
               run_id: str | None = None) -> SupervisorResult:
        if self.store is None:
            return super().handle(text, image_path)

        state = self.store.load()
        if state is None or state.status in ("done", "failed"):
            if state is not None and state.status == "done":
                # 이미 끝난 요청을 다시 부르면 재실행하지 않고 저장된 결과를 재생한다(멱등).
                return self._replay(state)
            req = AgentRequest(text=text, image_path=image_path, context={})
            plan = self.router.plan(req, self.agents)
            state = RunState(
                run_id=run_id or f"run-{int(time.time() * 1000)}",
                request=text, image_path=image_path,
                router=plan.router, reason=plan.reason, plan_steps=list(plan.steps),
            )
            self.store.save(state)
        # 재개: 계획은 다시 세우지 않고 체크포인트의 것을 그대로 쓴다(설계 결정 1).
        plan = RoutePlan(steps=list(state.plan_steps), router=state.router, reason=state.reason)

        t_start = time.perf_counter()
        ctx: dict = {}
        for name in state.plan_steps:
            if name in state.completed:
                ctx[name] = self._ctx_entry(_result_from_dict(state.completed[name]))
                self.resumed_steps += 1
                continue
            if self.budget_s is not None and (time.perf_counter() - t_start) > self.budget_s:
                state.status = "paused"
                self.store.save(state)
                break

            res = self._run_step_with_retry(state, name, text, image_path, ctx)
            state.completed[name] = _result_to_dict(res)
            ctx[name] = self._ctx_entry(res)
            self.store.save(state)   # 매 단계 후 원자적 저장 — 여기서 죽어도 이 단계까지는 남는다

        done = all(s in state.completed for s in state.plan_steps)
        if done:
            state.status = "done"
            self.store.save(state)
        return self._finalize(state, plan, t_start)

    # ------------------------------------------------------------ 내부
    def _run_step_with_retry(self, state: RunState, name: str, text: str,
                             image_path: str | None, ctx: dict) -> AgentResult:
        agent = self.agents[name]
        last: AgentResult | None = None
        used = 0

        for attempt in range(1, self.retry.max_attempts + 1):
            used = attempt
            step_ctx = dict(ctx)
            # 멱등 키 — 외부 액션을 가진 에이전트가 중복 발행을 스스로 막을 수 있게 한다.
            step_ctx["_idempotency_key"] = f"{state.run_id}:{name}"
            try:
                res = agent.run(AgentRequest(text=text, image_path=image_path, context=step_ctx))
            except Exception as e:                      # 예외도 결과로 흡수해 요청을 잃지 않는다
                res = AgentResult(agent=name, ok=False, summary=f"단계 실패: {e}",
                                  confidence=0.0, needs_human=True, error="exception")
            res.summary = redact_secrets(res.summary)
            last = res
            if res.ok:
                break
            if not self.retry.is_retryable(res.error):  # 설계 결정 3
                break
            if attempt < self.retry.max_attempts:
                self.retried_steps += 1
                d = self.retry.delay(attempt)
                if d > 0:
                    time.sleep(d)

        state.attempts[name] = state.attempts.get(name, 0) + used
        assert last is not None
        if not last.ok and self.retry.is_retryable(last.error) and used >= self.retry.max_attempts:
            # 설계 결정 4 — 내구 층이 만든 실패 유형이므로 내구 층이 사람검토로 올린다.
            self.exhausted_steps += 1
            last.needs_human = True
            last.confidence = 0.0
            last.error = last.error or "retries_exhausted"
            last.summary += f" (재시도 {used}회 소진)"
        return last

    @staticmethod
    def _ctx_entry(res: AgentResult) -> dict:
        return {"summary": res.summary, "confidence": res.confidence,
                "needs_human": res.needs_human, "ok": res.ok, "data": res.data}

    def _finalize(self, state: RunState, plan: RoutePlan, t_start: float) -> SupervisorResult:
        results = [_result_from_dict(state.completed[s])
                   for s in state.plan_steps if s in state.completed]
        steps = [StepRecord(agent=r.agent, ok=r.ok, latency_ms=0, confidence=r.confidence,
                            needs_human=r.needs_human, error=r.error) for r in results]
        needs_human = any(r.needs_human for r in results) or state.status == "paused"
        ok = all(r.ok for r in results) and state.status != "paused"
        answer = redact_secrets(self._synthesize(plan, results, needs_human))
        if state.status == "paused":
            answer += "\n\n⏸ 시간 예산 초과 — 남은 단계는 체크포인트에 보존됐습니다(재개 가능)."

        trace = RequestTrace(
            ts=now_iso(), request=state.request, router=plan.router, route=list(plan.steps),
            steps=steps, total_latency_ms=int((time.perf_counter() - t_start) * 1000),
            ok=ok, needs_human=needs_human,
        )
        if self.tracer is not None:
            self.tracer.emit(trace)
        return SupervisorResult(answer=answer, plan=plan, results=results,
                                needs_human=needs_human, ok=ok, trace=trace)

    def _replay(self, state: RunState) -> SupervisorResult:
        """완료된 요청의 저장된 결과를 그대로 재생(재실행 없음)."""
        plan = RoutePlan(steps=list(state.plan_steps), router=state.router, reason=state.reason)
        self.resumed_steps += len(state.completed)
        return self._finalize(state, plan, time.perf_counter())
