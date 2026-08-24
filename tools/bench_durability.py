"""내구 실행(durable execution) 벤치마크 — 장애가 섞인 환경에서 멀티에이전트 실행이 무엇을 잃는가.

왜 만들었나: 업스테이지 AI Engineer-Agents JD 우대사항에 "상태 저장, 재시도, 장애 복구를 포함한
장기 실행 AI 워크플로우 설계 경험"이 있는데, 이 레포의 supervisor는 단계 결과를 **메모리에만** 두고
재시도가 없다. "없다"를 고치기 전에 **없어서 무엇이 깨지는지부터 수치로** 잡는다.

측정 대상(3구성, 같은 고장 스케줄을 공유해 짝지음 비교):
  A. 현재         — 재시도·체크포인트 없음(`Supervisor` 그대로)
  B. 순진한 재시도 — 실패하면 **요청 전체**를 처음부터 다시(최대 3회)
  C. 내구 실행     — 체크포인트 + **단계 단위** 재시도 + 멱등 부작용(`app/durable.py`)

고장 모델(명시): 각 (요청, 단계)마다 시드된 RNG로 "몇 번째 시도까지 실패하는가"(k)를 뽑는다.
  - 확률 p_transient 로 일시 고장 → k회 실패 후 성공(LLM 429·네트워크 순단 모델)
  - 확률 p_permanent 로 영구 고장 → 몇 번을 재시도해도 실패(재시도가 만능이 아님을 보이려 넣는다)
  같은 스케줄을 A·B·C가 그대로 재생하므로 세 구성의 차이는 오직 **복구 전략**이다.

고장 주입 방식 2종(실제 코드가 둘 다 일으키므로 둘 다 잰다):
  - soft: 에이전트가 자기 예외를 잡아 `ok=False`를 반환(vision·analytics의 실제 동작)
  - hard: 예외가 그대로 올라옴(`llm.py`가 429 3회 후 raise 하는 경로)

지표: 완주율 · **오도 리포트 수** · 부작용 발행/중복 · 재실행 스텝(낭비) · 총 호출 · 소요 시간
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import AGENT_ORDER  # noqa: E402
from app.agents.base import AgentRequest, AgentResult, BaseAgent, Evidence  # noqa: E402
from app.reporting import build_report  # noqa: E402
from app.router import RoutePlan  # noqa: E402
from app.supervisor import Supervisor  # noqa: E402
from app.trace import Tracer  # noqa: E402


class TransientError(RuntimeError):
    """일시 고장(재시도하면 언젠가 성공)."""


class PermanentError(RuntimeError):
    """영구 고장(재시도해도 성공하지 않음)."""


# ---------------------------------------------------------------- 고장 스케줄
@dataclass
class FaultSchedule:
    """(요청, 단계) → 몇 번째 시도까지 실패하는가. None이면 영구 고장.

    A·B·C가 **같은 인스턴스**를 공유해 재생하므로 비교가 짝지어진다.
    """

    fail_until: dict

    @classmethod
    def draw(cls, n_runs: int, steps: tuple, p_transient: float,
             p_permanent: float, max_k: int, seed: int) -> "FaultSchedule":
        rng = random.Random(seed)
        table: dict = {}
        for r in range(n_runs):
            for s in steps:
                u = rng.random()
                if u < p_permanent:
                    table[(r, s)] = None                    # 영구 고장
                elif u < p_permanent + p_transient:
                    table[(r, s)] = rng.randint(1, max_k)   # k회 실패 후 성공
                else:
                    table[(r, s)] = 0                       # 무고장
        return cls(table)

    def fails(self, run_idx: int, step: str, attempt: int) -> bool:
        """attempt는 1부터. 이 시도가 실패해야 하는가."""
        k = self.fail_until.get((run_idx, step), 0)
        if k is None:
            return True
        return attempt <= k

    def is_permanent(self, run_idx: int, step: str) -> bool:
        return self.fail_until.get((run_idx, step), 0) is None


# ---------------------------------------------------------------- 부작용 원장
class SideEffectLedger:
    """외부 부작용(검사 성적서 발행)을 세는 원장.

    운영에서 리포트 발행은 MES/QMS로 나가는 **되돌릴 수 없는 액션**이다.
    같은 논리적 요청에 2건 이상 찍히면 중복 발행이다.
    """

    def __init__(self) -> None:
        self.rows: list = []   # (run_idx, idempotency_key)
        self.suppressed = 0    # 멱등 키로 막힌 재발행 횟수

    def issue(self, run_idx: int, key: str) -> bool:
        if any(k == key for _, k in self.rows):
            self.suppressed += 1
            return False
        self.rows.append((run_idx, key))
        return True

    @property
    def total(self) -> int:
        return len(self.rows)

    def duplicates(self) -> int:
        """같은 요청에 2건 이상 발행된 초과분."""
        per_run: dict = {}
        for r, _ in self.rows:
            per_run[r] = per_run.get(r, 0) + 1
        return sum(v - 1 for v in per_run.values() if v > 1)


# ---------------------------------------------------------------- 고장 에이전트
class FlakyAgent(BaseAgent):
    """실 에이전트 자리에 끼워 외부 의존성 고장을 주입한다. 성공 경로는 결정적."""

    def __init__(self, name: str, schedule: FaultSchedule, counter: dict,
                 mode: str, ledger: SideEffectLedger | None = None,
                 fault_sets_human: bool = False) -> None:
        self.name = name
        self.description = f"{name} 에이전트(벤치마크 스텁)"
        self.keywords = ()
        self.schedule = schedule
        self.counter = counter          # {"calls": int, "run_idx": int, "attempts": {step: n}}
        self.mode = mode                # "soft" | "hard"
        self.ledger = ledger
        # 실패 시 needs_human을 세우는가. 레포 실측: ok=False 반환 지점 6곳 중 5곳은 세우고,
        # vision의 no_image 1곳은 세우지 않는다. 두 모델을 다 돌려 결함의 실제 크기를 가른다.
        self.fault_sets_human = fault_sets_human

    def run(self, req: AgentRequest) -> AgentResult:
        run_idx = self.counter["run_idx"]
        self.counter["calls"] += 1
        self.counter["attempts"][self.name] = self.counter["attempts"].get(self.name, 0) + 1
        attempt = self.counter["attempts"][self.name]

        if self.schedule.fails(run_idx, self.name, attempt):
            permanent = self.schedule.is_permanent(run_idx, self.name)
            if self.mode == "hard":
                raise (PermanentError if permanent else TransientError)(
                    f"{self.name} 호출 실패(attempt {attempt})")
            # soft: 실제 에이전트들이 하듯 자기 예외를 잡아 ok=False로 반환.
            #       needs_human을 세우지 않는 경로가 실재한다(vision의 no_image 등).
            return AgentResult(
                agent=self.name, ok=False,
                summary=f"{self.name} 외부 호출 실패(attempt {attempt}).",
                confidence=0.0 if self.fault_sets_human else 1.0,
                needs_human=self.fault_sets_human,
                error="permanent" if permanent else "transient",
            )

        if self.name == "report" and self.ledger is not None:
            # 부작용: 성적서 발행. 멱등 키가 없으면 재실행마다 새로 찍힌다.
            key = req.context.get("_idempotency_key") or f"run{run_idx}:call{attempt}"
            self.ledger.issue(run_idx, key)

        return AgentResult(
            agent=self.name, ok=True, summary=f"{self.name} 정상 완료.",
            evidence=[Evidence(source=self.name, detail="bench stub")],
            confidence=0.95,
        )


class FixedPlanRouter:
    """벤치마크는 라우팅이 아니라 복구 전략을 재므로 계획을 고정한다."""

    def __init__(self, steps: tuple) -> None:
        self.steps = list(steps)

    def plan(self, req, agents) -> RoutePlan:
        return RoutePlan(steps=list(self.steps), router="fixed(bench)", reason="벤치마크 고정 계획")


# ---------------------------------------------------------------- 판정
def report_is_misleading(step_ok: dict, step_human: dict | None = None) -> bool:
    """실패 단계가 있는데도 리포트가 '자동 판정 신뢰 가능'이라고 말하는가."""
    step_human = step_human or {}
    records = {
        name: {"summary": "", "confidence": 0.95,
               "needs_human": bool(step_human.get(name, False)), "ok": ok}
        for name, ok in step_ok.items()
    }
    rep = build_report("bench", records)
    any_failed = not all(step_ok.values())
    return any_failed and not rep.needs_human and rep.recommendation.startswith("자동 판정 신뢰 가능")


@dataclass
class Outcome:
    completed: int = 0          # 모든 계획 단계가 ok
    misleading: int = 0         # 오도 리포트
    lost: int = 0               # 예외로 답 자체를 못 낸 요청(hard 모드)
    calls: int = 0              # 총 에이전트 호출
    seconds: float = 0.0
    side_effects: int = 0
    duplicate_effects: int = 0
    replayed_steps: int = 0     # 이미 성공한 단계를 다시 실행한 횟수(낭비)


# ---------------------------------------------------------------- 구성 A / B
def run_baseline(n_runs: int, steps: tuple, schedule: FaultSchedule,
                 mode: str, retries: int, fault_sets_human: bool = False) -> Outcome:
    """A(retries=1) / B(retries=3, 요청 전체 재실행) 공통 실행기."""
    out = Outcome()
    ledger = SideEffectLedger()
    t0 = time.perf_counter()

    for r in range(n_runs):
        counter = {"calls": 0, "run_idx": r, "attempts": {}}
        agents = {s: FlakyAgent(s, schedule, counter, mode, ledger, fault_sets_human)
                  for s in steps}
        sup = Supervisor(agents=agents, router=FixedPlanRouter(steps),
                         tracer=Tracer(path="", echo=False))
        step_ok: dict = {}
        step_human: dict = {}
        lost = False
        prev_success: set = set()

        for attempt in range(retries):
            if attempt > 0:
                # 요청 전체 재실행 = 이미 성공한 단계도 다시 태운다(낭비를 여기서 센다).
                out.replayed_steps += len(prev_success)
            try:
                res = sup.handle(f"요청 {r}")
                step_ok = {x.agent: x.ok for x in res.results}
                step_human = {x.agent: x.needs_human for x in res.results}
                prev_success = {k for k, v in step_ok.items() if v}
                lost = False
            except Exception:
                lost = True
                step_ok = {}
                step_human = {}
                prev_success = set()
            if not lost and all(step_ok.values()):
                break

        out.calls += counter["calls"]
        if lost:
            out.lost += 1
            continue
        if step_ok and all(step_ok.values()):
            out.completed += 1
        if step_ok:
            out.misleading += int(report_is_misleading(step_ok, step_human))

    out.seconds = time.perf_counter() - t0
    out.side_effects = ledger.total
    out.duplicate_effects = ledger.duplicates()
    return out


# ---------------------------------------------------------------- 구성 C
def run_durable(n_runs: int, steps: tuple, schedule: FaultSchedule, mode: str,
                max_attempts: int, store_dir: Path,
                fault_sets_human: bool = False) -> Outcome:
    from app.durable import DurableSupervisor, FileCheckpointStore, RetryPolicy

    out = Outcome()
    ledger = SideEffectLedger()
    t0 = time.perf_counter()

    for r in range(n_runs):
        counter = {"calls": 0, "run_idx": r, "attempts": {}}
        agents = {s: FlakyAgent(s, schedule, counter, mode, ledger, fault_sets_human)
                  for s in steps}
        store = FileCheckpointStore(store_dir / f"run{r}.json")
        sup = DurableSupervisor(
            agents=agents, router=FixedPlanRouter(steps),
            tracer=Tracer(path="", echo=False), store=store,
            retry=RetryPolicy(max_attempts=max_attempts, base_delay_s=0.0),
        )
        try:
            res = sup.handle(f"요청 {r}", run_id=f"run{r}")
            step_ok = {x.agent: x.ok for x in res.results}
            step_human = {x.agent: x.needs_human for x in res.results}
            if step_ok and all(step_ok.values()):
                out.completed += 1
            if step_ok:
                out.misleading += int(report_is_misleading(step_ok, step_human))
        except Exception:
            out.lost += 1
        out.calls += counter["calls"]
        out.replayed_steps += sup.replayed_steps

    out.seconds = time.perf_counter() - t0
    out.side_effects = ledger.total
    out.duplicate_effects = ledger.duplicates()
    return out


# ---------------------------------------------------------------- 출력
def emit(name: str, o: Outcome, n: int) -> dict:
    row = {
        "구성": name,
        "완주율": round(100 * o.completed / n, 1),
        "오도리포트": o.misleading,
        "요청유실": o.lost,
        "부작용발행": o.side_effects,
        "중복발행": o.duplicate_effects,
        "재실행스텝": o.replayed_steps,
        "총호출": o.calls,
        "초": round(o.seconds, 3),
    }
    print(json.dumps(row, ensure_ascii=False))
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--p-transient", type=float, default=0.25)
    ap.add_argument("--p-permanent", type=float, default=0.03)
    ap.add_argument("--max-k", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--mode", choices=["soft", "hard", "both"], default="both")
    ap.add_argument("--configs", default="ABC", help="실행할 구성(A/B/C 조합). 예: AB")
    ap.add_argument("--fault-sets-human", action="store_true",
                    help="실패 시 needs_human=True를 세우는 규율 있는 에이전트로 모델링")
    ap.add_argument("--out", default="tools/bench_durability_result.json")
    args = ap.parse_args()

    steps = AGENT_ORDER  # vision → analytics → knowledge → report
    modes = ["soft", "hard"] if args.mode == "both" else [args.mode]
    store_dir = Path(".bench_ckpt")
    results: dict = {}

    for mode in modes:
        schedule = FaultSchedule.draw(args.runs, steps, args.p_transient,
                                      args.p_permanent, args.max_k, args.seed)
        print(f"\n=== mode={mode} · runs={args.runs} · p_transient={args.p_transient} "
              f"· p_permanent={args.p_permanent} · max_k={args.max_k} · seed={args.seed} ===")
        rows = []
        if "A" in args.configs:
            rows.append(emit("A 현재(재시도 없음)",
                             run_baseline(args.runs, steps, schedule, mode, 1, args.fault_sets_human), args.runs))
        if "B" in args.configs:
            rows.append(emit("B 순진한 재시도(전체 3회)",
                             run_baseline(args.runs, steps, schedule, mode, 3, args.fault_sets_human), args.runs))
        if "C" in args.configs:
            if store_dir.exists():
                shutil.rmtree(store_dir)
            store_dir.mkdir(parents=True, exist_ok=True)
            rows.append(emit("C 내구 실행(체크포인트+단계재시도+멱등)",
                             run_durable(args.runs, steps, schedule, mode, 3, store_dir, args.fault_sets_human),
                             args.runs))
        results[mode] = rows

    meta = {"fault_sets_human": args.fault_sets_human,
            "runs": args.runs, "p_transient": args.p_transient,
            "p_permanent": args.p_permanent, "max_k": args.max_k,
            "seed": args.seed, "steps": list(steps)}
    Path(args.out).write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
