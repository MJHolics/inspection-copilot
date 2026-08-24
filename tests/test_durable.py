"""내구 실행 층 테스트 — 체크포인트·재시도·멱등·재개. 전부 오프라인·결정적.

여기서 강제하는 불변식은 `tools/bench_durability.py`·`tools/bench_crash_resume.py`가 수치로
보여준 것들의 회귀 방지판이다. 특히 "성공한 단계는 두 번 실행하지 않는다"와 "재시도를 소진한
단계는 사람검토로 올라간다"는 깨지면 조용히 잘못된 리포트가 나가는 종류라 테스트로 못 박는다.
"""
from __future__ import annotations

import json

import pytest

from app.agents.base import AgentRequest, AgentResult, BaseAgent, Evidence
from app.durable import (NON_RETRYABLE, DurableSupervisor, FileCheckpointStore,
                         MemoryCheckpointStore, RetryPolicy, RunState)
from app.router import RoutePlan
from app.supervisor import Supervisor
from app.trace import Tracer

STEPS = ("vision", "analytics", "report")


class CountingAgent(BaseAgent):
    """호출 횟수를 세고, 지정한 횟수만큼 실패한 뒤 성공하는 에이전트."""

    def __init__(self, name: str, fail_times: int = 0, error: str = "transient",
                 raises: bool = False, log: list | None = None) -> None:
        self.name = name
        self.description = name
        self.keywords = ()
        self.fail_times = fail_times
        self.error = error
        self.raises = raises
        self.calls = 0
        self.keys: list = []
        self.log = log if log is not None else []

    def run(self, req: AgentRequest) -> AgentResult:
        self.calls += 1
        self.log.append(self.name)
        self.keys.append(req.context.get("_idempotency_key"))
        if self.calls <= self.fail_times:
            if self.raises:
                raise RuntimeError(f"{self.name} 폭발")
            return AgentResult(agent=self.name, ok=False, summary="실패", error=self.error)
        return AgentResult(agent=self.name, ok=True, summary=f"{self.name} ok",
                           evidence=[Evidence(source=self.name, detail="t")], confidence=0.9)


class FixedRouter:
    def __init__(self, steps=STEPS) -> None:
        self.steps = list(steps)
        self.calls = 0

    def plan(self, req, agents) -> RoutePlan:
        self.calls += 1
        return RoutePlan(steps=list(self.steps), router="fixed", reason="테스트")


def _sup(agents, store=None, **kw) -> DurableSupervisor:
    return DurableSupervisor(agents=agents, router=kw.pop("router", None) or FixedRouter(),
                             tracer=Tracer(path="", echo=False), store=store,
                             retry=kw.pop("retry", RetryPolicy(max_attempts=3, base_delay_s=0.0)),
                             **kw)


def _agents(**overrides) -> dict:
    a = {s: CountingAgent(s) for s in STEPS}
    a.update(overrides)
    return a


# ---------------------------------------------------------------- 기존 경로 무영향
def test_store_none_matches_plain_supervisor():
    """store를 안 주면 부모 Supervisor와 같은 답을 낸다(데모·서버 경로 무영향)."""
    a1, a2 = _agents(), _agents()
    plain = Supervisor(agents=a1, router=FixedRouter(), tracer=Tracer(path="", echo=False))
    dur = _sup(a2, store=None)
    assert dur.handle("질문").answer == plain.handle("질문").answer


# ---------------------------------------------------------------- 체크포인트
def test_checkpoint_written_with_plan_and_results(tmp_path):
    store = FileCheckpointStore(tmp_path / "ck.json")
    _sup(_agents(), store=store).handle("질문", run_id="r1")
    saved = json.loads((tmp_path / "ck.json").read_text(encoding="utf-8"))
    assert saved["run_id"] == "r1"
    assert saved["plan_steps"] == list(STEPS)
    assert set(saved["completed"]) == set(STEPS)
    assert saved["status"] == "done"


def test_resume_skips_completed_steps():
    """중간까지 끝난 체크포인트에서 재개하면 끝난 단계는 다시 실행하지 않는다."""
    store = MemoryCheckpointStore()
    store.save(RunState(run_id="r1", request="질문", plan_steps=list(STEPS),
                        completed={"vision": {"agent": "vision", "ok": True, "summary": "이전",
                                              "evidence": [], "confidence": 0.9,
                                              "needs_human": False, "data": {}, "error": None}}))
    agents = _agents()
    sup = _sup(agents, store=store)
    res = sup.handle("질문", run_id="r1")
    assert agents["vision"].calls == 0          # 이미 끝난 단계 — 재실행 없음
    assert agents["analytics"].calls == 1
    assert sup.resumed_steps == 1
    assert sup.replayed_steps == 0              # 낭비 재실행 0이 설계 목표
    assert res.ok


def test_completed_run_replays_without_reexecuting():
    """끝난 요청을 같은 run_id로 다시 부르면 저장된 결과를 재생하고 에이전트를 부르지 않는다."""
    store = MemoryCheckpointStore()
    agents = _agents()
    first = _sup(agents, store=store).handle("질문", run_id="r1")
    calls_after_first = {k: v.calls for k, v in agents.items()}
    second = _sup(agents, store=store).handle("질문", run_id="r1")
    assert {k: v.calls for k, v in agents.items()} == calls_after_first
    assert second.answer == first.answer


def test_corrupted_checkpoint_is_treated_as_absent(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text('{"run_id": "r1", "plan', encoding="utf-8")   # 잘린 JSON
    store = FileCheckpointStore(p)
    assert store.load() is None
    assert _sup(_agents(), store=store).handle("질문", run_id="r1").ok


def test_atomic_write_leaves_no_tmp_files(tmp_path):
    store = FileCheckpointStore(tmp_path / "ck.json")
    _sup(_agents(), store=store).handle("질문", run_id="r1")
    assert list(tmp_path.glob("*.tmp")) == []


def test_nofsync_store_still_writes_valid_checkpoint(tmp_path):
    """fsync를 꺼도(프로세스 사망 위협 모델) 체크포인트는 온전해야 한다."""
    store = FileCheckpointStore(tmp_path / "ck.json", fsync=False)
    _sup(_agents(), store=store).handle("질문", run_id="r1")
    assert store.load().status == "done"


# ---------------------------------------------------------------- 재시도
def test_transient_failure_is_retried_and_succeeds():
    agents = _agents(analytics=CountingAgent("analytics", fail_times=2))
    sup = _sup(agents, store=MemoryCheckpointStore())
    res = sup.handle("질문", run_id="r1")
    assert agents["analytics"].calls == 3
    assert res.ok and all(r.ok for r in res.results)


def test_successful_step_is_never_retried():
    agents = _agents(analytics=CountingAgent("analytics", fail_times=1))
    _sup(agents, store=MemoryCheckpointStore()).handle("질문", run_id="r1")
    assert agents["vision"].calls == 1      # 앞 단계는 analytics 재시도에 말려들지 않는다
    assert agents["report"].calls == 1


def test_exhausted_retries_escalate_to_human():
    """재시도를 다 쓰면 사람검토로 올린다 — 에이전트의 플래그 규율에 기대지 않는다."""
    agents = _agents(analytics=CountingAgent("analytics", fail_times=99))
    sup = _sup(agents, store=MemoryCheckpointStore())
    res = sup.handle("질문", run_id="r1")
    bad = [r for r in res.results if r.agent == "analytics"][0]
    assert agents["analytics"].calls == 3
    assert bad.ok is False and bad.needs_human is True and bad.confidence == 0.0
    assert res.needs_human is True and sup.exhausted_steps == 1


@pytest.mark.parametrize("err", sorted(NON_RETRYABLE))
def test_non_retryable_errors_are_not_retried(err):
    """재시도해도 나아지지 않는 실패는 한 번만 부르고 확정한다."""
    agents = _agents(vision=CountingAgent("vision", fail_times=99, error=err))
    sup = _sup(agents, store=MemoryCheckpointStore())
    sup.handle("질문", run_id="r1")
    assert agents["vision"].calls == 1
    assert sup.exhausted_steps == 0     # 소진이 아니라 즉시 확정


def test_exception_is_absorbed_not_propagated():
    """예외가 올라와도 요청을 통째로 잃지 않는다(hard 고장 → 유실 0)."""
    agents = _agents(vision=CountingAgent("vision", fail_times=99, raises=True))
    sup = _sup(agents, store=MemoryCheckpointStore())
    res = sup.handle("질문", run_id="r1")
    v = [r for r in res.results if r.agent == "vision"][0]
    assert v.ok is False and v.error == "exception" and v.needs_human is True
    assert agents["report"].calls == 1      # 뒤 단계는 계속 진행된다


def test_retry_policy_backoff_grows_and_caps():
    p = RetryPolicy(max_attempts=5, base_delay_s=1.0, max_delay_s=4.0, jitter=0.0, seed=0)
    assert [p.delay(i) for i in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 4.0]
    assert RetryPolicy(base_delay_s=0.0).delay(1) == 0.0


# ---------------------------------------------------------------- 멱등성
def test_idempotency_key_is_stable_per_run_and_step():
    """같은 (run_id, 단계)의 재시도는 같은 키를 받는다 — 하류가 중복을 접을 수 있다."""
    agents = _agents(report=CountingAgent("report", fail_times=2))
    _sup(agents, store=MemoryCheckpointStore()).handle("질문", run_id="r1")
    assert agents["report"].keys == ["r1:report"] * 3
    assert agents["vision"].keys == ["r1:vision"]


# ---------------------------------------------------------------- 계획 고정
def test_plan_is_not_recomputed_on_resume():
    """재개 시 라우터를 다시 부르지 않는다 — 계획이 바뀌면 끝난 작업이 무효가 된다."""
    store = MemoryCheckpointStore()
    router = FixedRouter()
    agents = _agents()
    _sup(agents, store=store, router=router).handle("질문", run_id="r1")
    assert router.calls == 1
    store.load().status = "running"     # 사본이라 원본 상태는 done 그대로
    _sup(_agents(), store=store, router=router).handle("질문", run_id="r1")
    assert router.calls == 1            # 재생 경로 — 라우터 호출 없음


# ---------------------------------------------------------------- 시간 예산
class SlowAgent(CountingAgent):
    """예산 초과를 확정적으로 만들기 위해 한 단계가 시간을 쓰게 한다."""

    def run(self, req: AgentRequest) -> AgentResult:
        import time
        time.sleep(0.05)
        return super().run(req)


def test_budget_pauses_after_completed_step_and_resumes():
    """예산을 넘기면 **끝난 단계는 보존하고** 남은 단계 앞에서 멈춘다 — 이어서 재개된다."""
    store = MemoryCheckpointStore()
    agents = _agents(vision=SlowAgent("vision"))
    sup = _sup(agents, store=store, budget_s=0.01)   # 1단계(0.05s) 후 초과
    res = sup.handle("질문", run_id="r1")

    assert store.load().status == "paused"
    assert set(store.load().completed) == {"vision"}     # 끝난 단계는 남았다
    assert res.needs_human is True and res.ok is False
    assert agents["vision"].calls == 1 and agents["analytics"].calls == 0

    agents2 = _agents()
    res2 = _sup(agents2, store=store).handle("질문", run_id="r1")     # 예산 없이 재개
    assert res2.ok
    assert agents2["vision"].calls == 0                  # 1단계는 이미 끝나 있다
    assert agents2["analytics"].calls == 1 and agents2["report"].calls == 1


def test_budget_zero_pauses_before_any_step():
    store = MemoryCheckpointStore()
    agents = _agents()
    _sup(agents, store=store, budget_s=-1.0).handle("질문", run_id="r1")
    assert store.load().status == "paused"
    assert sum(a.calls for a in agents.values()) == 0     # 한 단계도 시작하지 않는다


# ---------------------------------------------------------------- 제품 배선
def test_service_durable_factory_shares_agents_with_default(tmp_path):
    """내구 supervisor는 `get_supervisor()`와 **같은 레지스트리·라우터**를 쓴다.

    측정한 구성과 배포된 구성이 갈리지 않게 하려는 기존 원칙(eval·service 단일 팩토리)의 연장이다.
    """
    from app.service import get_durable_supervisor, get_supervisor

    base = get_supervisor()
    dur = get_durable_supervisor("t1", runs_dir=tmp_path)
    assert dur.agents is base.agents
    assert dur.router is base.router


def test_service_durable_factory_defaults_to_no_fsync(tmp_path):
    """기본 위협 모델은 프로세스 사망이라 fsync를 켜지 않는다(단계당 3.41ms → 1.37ms)."""
    from app.service import get_durable_supervisor

    assert get_durable_supervisor("t2", runs_dir=tmp_path).store.fsync is False
    assert get_durable_supervisor("t3", runs_dir=tmp_path, fsync=True).store.fsync is True


def test_service_durable_run_creates_checkpoint_and_replays(tmp_path):
    from app.service import get_durable_supervisor

    first = get_durable_supervisor("t4", runs_dir=tmp_path)
    first.handle("스크래치 결함 처리 절차 알려줘", run_id="t4")
    assert (tmp_path / "t4.json").exists()

    second = get_durable_supervisor("t4", runs_dir=tmp_path)
    second.handle("스크래치 결함 처리 절차 알려줘", run_id="t4")
    assert second.resumed_steps > 0      # 재실행 없이 저장된 결과를 재생
