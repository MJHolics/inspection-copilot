"""배치 전송으로 바꾼 대가 — 프로세스가 강제 종료되면 트레이스를 얼마나 잃는가.

bench_langfuse.py는 배치가 요청 지연을 58ms→0.4ms로 줄인다는 걸 보였다. 그 대가는 "아직 안 보낸
배치"다. SDK는 정상 종료 시 atexit로 flush하지만, 크래시·OOM kill·컨테이너 강제 종료에서는 atexit가
돌지 않는다. 이 스크립트는 그 상황을 `os._exit()`(atexit 건너뜀)로 재현해 유실량을 잰다.

  flush_each            요청마다 flush — 유실 기준선(0이어야 한다)
  batch_interval_5s     SDK 기본값(LANGFUSE_FLUSH_INTERVAL=5)
  batch_interval_1s     전송 주기를 1초로 줄였을 때

부하: 요청 사이 50ms 휴지(≈초당 18건)로 12초 동안 돌린 뒤 즉시 강제 종료.

사용:
    python tools/bench_langfuse_crash.py      # → tools/bench_langfuse_crash_result.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_langfuse import ROOT, _count_arrived  # noqa: E402

OUT = ROOT / "tools" / "bench_langfuse_crash_result.json"
DURATION_S = 12.0
GAP_S = 0.05

CASES = {
    "flush_each":        {"LANGFUSE_FLUSH_EACH": "1"},
    "batch_interval_5s": {"LANGFUSE_FLUSH_EACH": "0", "LANGFUSE_FLUSH_INTERVAL": "5"},
    "batch_interval_1s": {"LANGFUSE_FLUSH_EACH": "0", "LANGFUSE_FLUSH_INTERVAL": "1"},
}


def _child() -> None:
    sys.path.insert(0, str(ROOT))
    from app import db, langfuse_trace
    from app.eval.run_eval import _build_supervisor, _stub_sql, _suite, evaluate_task
    from app.retrieval import make_grounding_retriever

    db.build_db()
    kn, tau = make_grounding_retriever("tfidf")
    sup = _build_supervisor(_stub_sql, knowledge_retriever=kn, grounding_tau=tau)
    tasks = _suite("all")
    assert langfuse_trace.enabled()

    sent, expected, i = 0, 0, 0
    t_end = time.perf_counter() + DURATION_S
    while time.perf_counter() < t_end:
        t = tasks[i % len(tasks)]
        c = evaluate_task(sup, t)
        sent += 1
        expected += 1 + len(c.route_pred)
        i += 1
        time.sleep(GAP_S)
    print(json.dumps({"sent": sent, "expected_spans": expected}), flush=True)
    os._exit(137)  # 크래시 재현: atexit(SDK의 자동 flush)가 돌지 않는다


def main() -> None:
    if "--child" in sys.argv:
        _child()
        return
    results = {}
    for name, over in CASES.items():
        env = {**os.environ, **over, "PYTHONIOENCODING": "utf-8", "TRACE_ECHO": "0"}
        t_start = datetime.now(timezone.utc).isoformat()
        p = subprocess.run([sys.executable, __file__, "--child"], env=env, capture_output=True,
                           text=True, encoding="utf-8", cwd=ROOT)
        t_stop = datetime.now(timezone.utc).isoformat()
        line = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if not line:
            results[name] = {"error": p.stderr[-600:]}
            print(f"[{name}] ERROR\n{p.stderr[-600:]}")
            continue
        r = json.loads(line[-1])
        r["returncode"] = p.returncode
        # 워커 적재 대기 후 도착 수 확정(값이 두 번 연속 같을 때까지)
        prev = None
        for _ in range(24):
            time.sleep(5)
            arrived = _count_arrived(t_start, t_stop)
            total = sum(arrived.values())
            if total == prev:
                break
            prev = total
        r["arrived_total"] = total
        r["lost_spans"] = r["expected_spans"] - total
        r["loss_rate"] = round(r["lost_spans"] / r["expected_spans"], 4)
        results[name] = r
        print(f"[{name}] rc={p.returncode} sent={r['sent']} expected={r['expected_spans']} "
              f"arrived={total} lost={r['lost_spans']} ({r['loss_rate']:.1%})")
        time.sleep(2)

    OUT.write_text(json.dumps({"measured_at": datetime.now().isoformat(timespec="seconds"),
                               "duration_s": DURATION_S, "gap_s": GAP_S, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
