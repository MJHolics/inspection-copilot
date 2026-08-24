"""체크포인트 비용 측정 — 내구성은 공짜가 아니다. 얼마인지 반복 측정해서 값을 매긴다.

`bench_durability.py`에서 구성 C의 소요 시간이 실행마다 2.5~4.7초로 흔들렸다. 흔들리는 값을
배수로 인용하지 않는다(이 레포의 기존 규칙: 표준편차가 평균의 절반을 넘는 지표는 배수 금지).
그래서 비용만 떼어 **5회 반복**하고 평균±표준편차로 보고한다.

세 저장소를 같은 워크로드로 비교한다:
  - none    : 체크포인트 없음(현재 Supervisor)
  - memory  : 인메모리 체크포인트 — 직렬화 비용만, 디스크·fsync 없음
  - file_nofsync : 파일 + 원자적 교체(`os.replace`), fsync 없음
                   → **프로세스 사망**(OOM 킬·컨테이너 교체·SIGKILL)에는 이것으로 충분하다
  - file    : 위 + fsync — **머신 전원 손실·커널 패닉**까지 견딘다

none→memory가 직렬화가 받는 값, memory→file_nofsync가 파일 I/O, file_nofsync→file이 fsync다.
위협 모델이 프로세스 사망이면 fsync 값은 안 내도 된다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.base import AgentRequest, AgentResult, BaseAgent, Evidence  # noqa: E402
from app.durable import (DurableSupervisor, FileCheckpointStore,  # noqa: E402
                         MemoryCheckpointStore, RetryPolicy)
from app.router import RoutePlan  # noqa: E402
from app.supervisor import Supervisor  # noqa: E402
from app.trace import Tracer  # noqa: E402

STEPS = ("vision", "analytics", "knowledge", "report")


class NoopAgent(BaseAgent):
    """비용 측정용 — 에이전트 자체는 거의 시간을 쓰지 않게 해 체크포인트 비용만 남긴다."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.keywords = ()

    def run(self, req: AgentRequest) -> AgentResult:
        return AgentResult(agent=self.name, ok=True, summary=f"{self.name} ok",
                           evidence=[Evidence(source=self.name, detail="cost bench")],
                           confidence=0.95)


class FixedRouter:
    def plan(self, req, agents) -> RoutePlan:
        return RoutePlan(steps=list(STEPS), router="fixed", reason="비용 측정")


def one_pass(kind: str, n: int, tmp: Path) -> float:
    agents = {s: NoopAgent(s) for s in STEPS}
    tracer = Tracer(path="", echo=False)
    t0 = time.perf_counter()
    for i in range(n):
        if kind == "none":
            Supervisor(agents=agents, router=FixedRouter(), tracer=tracer).handle("요청")
        else:
            if kind == "memory":
                store = MemoryCheckpointStore()
            else:
                store = FileCheckpointStore(tmp / f"r{i}.json",
                                            fsync=(kind == "file"))
            DurableSupervisor(agents=agents, router=FixedRouter(), tracer=tracer,
                              store=store,
                              retry=RetryPolicy(max_attempts=3, base_delay_s=0.0),
                              ).handle("요청", run_id=f"r{i}")
    return time.perf_counter() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--out", default="tools/bench_checkpoint_cost_result.json")
    args = ap.parse_args()

    import shutil
    tmp = ROOT / ".cost_ckpt"
    rows = []
    for kind in ("none", "memory", "file_nofsync", "file"):
        samples = []
        for _ in range(args.repeat):
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True, exist_ok=True)
            samples.append(one_pass(kind, args.runs, tmp))
        mean = statistics.mean(samples)
        sd = statistics.stdev(samples) if len(samples) > 1 else 0.0
        per_step_ms = 1000 * mean / (args.runs * len(STEPS))
        row = {
            "저장소": kind,
            "평균_초": round(mean, 4),
            "표준편차_초": round(sd, 4),
            "CV_%": round(100 * sd / mean, 1) if mean else 0.0,
            "단계당_ms": round(per_step_ms, 4),
            "표본": [round(s, 4) for s in samples],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    shutil.rmtree(tmp, ignore_errors=True)
    base = next(r for r in rows if r["저장소"] == "none")["평균_초"]
    for r in rows:
        r["none_대비_배수"] = round(r["평균_초"] / base, 2) if base else None
    meta = {"runs": args.runs, "repeat": args.repeat, "steps": list(STEPS),
            "note": "에이전트는 no-op. 차이는 체크포인트(직렬화/fsync) 비용이다."}
    Path(args.out).write_text(json.dumps({"meta": meta, "rows": rows},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
