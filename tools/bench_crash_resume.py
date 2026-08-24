"""크래시–재개 테스트 — 시뮬레이션이 아니라 **프로세스를 실제로 죽여서** 잰다.

`bench_durability.py`는 고장을 값(ok=False)이나 예외로 주입한다. 그건 프로세스가 살아 있는
경우다. 정말 알고 싶은 것은 **프로세스가 통째로 사라졌을 때** 무엇이 남는가다(OOM 킬·배포 중
컨테이너 교체·SIGKILL). 그래서 자식 프로세스를 띄워 지정한 단계에서 `os._exit(137)`로 죽인다 —
`atexit`도, `finally`도, 버퍼 flush도 돌지 않는 진짜 강제 종료다.

측정: 자식1(죽음) → 자식2(재개)를 돌리고
  - 실제로 실행된 단계 수(작업 원장 `work.log`에 append-only로 기록 — 프로세스가 죽어도 남는다)
  - 부작용 발행 횟수(논리적 요청 1건당 1건이어야 한다)
  - 재개가 성공해 최종 답이 나오는가
를 **현재 Supervisor(체크포인트 없음)** 와 **DurableSupervisor** 에 대해 각각 본다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STEPS = ("vision", "analytics", "knowledge", "report")


# ---------------------------------------------------------------- 자식 프로세스
CHILD = r'''
import os, sys, json
from pathlib import Path
sys.path.insert(0, r"{root}")
from app.agents.base import AgentRequest, AgentResult, BaseAgent, Evidence
from app.supervisor import Supervisor
from app.trace import Tracer

WORK = Path(os.environ["WORK_LOG"])
EFFECT = Path(os.environ["EFFECT_LOG"])
CRASH_AT = os.environ.get("CRASH_AT", "")
DURABLE = os.environ.get("DURABLE", "0") == "1"
RUN_ID = os.environ["RUN_ID"]

class Step(BaseAgent):
    def __init__(self, name):
        self.name = name; self.description = name; self.keywords = ()
    def run(self, req):
        # 작업 원장: 이 단계가 실제로 실행됐다는 지워지지 않는 흔적(append + flush + fsync).
        with open(WORK, "a", encoding="utf-8") as f:
            f.write(self.name + "\n"); f.flush(); os.fsync(f.fileno())
        if self.name == "report":
            # 멱등 키가 없으면 실행마다 새 성적서 번호가 매겨진다(실제 발번 로직 모델).
            key = req.context.get("_idempotency_key") or f"{{RUN_ID}}:pid{{os.getpid()}}"
            with open(EFFECT, "a", encoding="utf-8") as f:
                f.write(key + "\n"); f.flush(); os.fsync(f.fileno())
        if self.name == CRASH_AT:
            os._exit(137)   # SIGKILL 상당 — 정리 코드 일절 없음
        return AgentResult(agent=self.name, ok=True, summary=f"{{self.name}} 완료",
                           evidence=[Evidence(source=self.name, detail="crash-test")],
                           confidence=0.95)

class FixedRouter:
    def plan(self, req, agents):
        from app.router import RoutePlan
        return RoutePlan(steps={steps!r}, router="fixed", reason="crash test")

agents = {{s: Step(s) for s in {steps!r}}}
tracer = Tracer(path="", echo=False)

if DURABLE:
    from app.durable import DurableSupervisor, FileCheckpointStore, RetryPolicy
    store = FileCheckpointStore(os.environ["CKPT"])
    sup = DurableSupervisor(agents=agents, router=FixedRouter(), tracer=tracer,
                            store=store, retry=RetryPolicy(max_attempts=3, base_delay_s=0.0))
    res = sup.handle("크래시 테스트 요청", run_id=RUN_ID)
    print(json.dumps({{"ok": res.ok, "resumed": sup.resumed_steps}}, ensure_ascii=False))
else:
    sup = Supervisor(agents=agents, router=FixedRouter(), tracer=tracer)
    res = sup.handle("크래시 테스트 요청")
    print(json.dumps({{"ok": res.ok, "resumed": 0}}, ensure_ascii=False))
'''


def run_child(script: Path, env: dict) -> tuple[int, str]:
    e = dict(os.environ)
    e.update(env)
    e["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       encoding="utf-8", env=e)
    return p.returncode, (p.stdout or "").strip()


def scenario(durable: bool, crash_at: str, work_dir: Path) -> dict:
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    script = work_dir / "child.py"
    script.write_text(CHILD.format(root=str(ROOT), steps=list(STEPS)), encoding="utf-8")

    env = {
        "WORK_LOG": str(work_dir / "work.log"),
        "EFFECT_LOG": str(work_dir / "effect.log"),
        "CKPT": str(work_dir / "ckpt.json"),
        "RUN_ID": "crash-run-1",
        "DURABLE": "1" if durable else "0",
    }

    rc1, out1 = run_child(script, {**env, "CRASH_AT": crash_at})
    rc2, out2 = run_child(script, {**env, "CRASH_AT": ""})   # 재개 시도(고장 없음)

    work = (work_dir / "work.log").read_text(encoding="utf-8").split() \
        if (work_dir / "work.log").exists() else []
    effects = (work_dir / "effect.log").read_text(encoding="utf-8").split() \
        if (work_dir / "effect.log").exists() else []
    split = len(work) - work[len(work):].count("")  # 전체 실행 단계 수
    resumed = 0
    try:
        resumed = json.loads(out2).get("resumed", 0)
    except Exception:
        pass

    return {
        "구성": "C 내구 실행" if durable else "A 현재(체크포인트 없음)",
        "죽인단계": crash_at,
        "1차_종료코드": rc1,
        "총_실행단계": split,
        "실행_순서": " ".join(work),
        "재개_성공": rc2 == 0,
        "재개시_건너뛴단계": resumed,
        "부작용_발행": len(effects),
        "중복_발행": max(0, len(effects) - 1),
        "고유키": len(set(effects)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crash-at", default="all",
                    choices=list(STEPS) + ["all"], help="어느 단계에서 죽일지. all=전 단계 순회")
    ap.add_argument("--out", default="tools/bench_crash_resume_result.json")
    args = ap.parse_args()

    base = ROOT / ".crash_test"
    rows = []
    points = list(STEPS) if args.crash_at == "all" else [args.crash_at]
    for crash_at in points:
        for durable in (False, True):
            tag = ("durable" if durable else "baseline") + "_" + crash_at
            row = scenario(durable, crash_at, base / tag)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))

    meta = {"crash_at": args.crash_at, "steps": list(STEPS),
            "note": "자식 프로세스를 os._exit(137)로 강제 종료 후 같은 run_id로 재실행"}
    Path(args.out).write_text(json.dumps({"meta": meta, "rows": rows},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(base, ignore_errors=True)
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
