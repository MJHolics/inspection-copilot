"""Langfuse 계측의 비용·유실·장애 영향을 잰다 — "붙였다"가 아니라 "붙이면 무엇이 바뀌는가".

같은 결정적 평가셋(golden+adversarial, LLM 키 불요 — SQL·비전은 스텁)을 모드별로 반복 실행한다.
모드마다 **별도 프로세스**로 돌린다(Langfuse v4 SDK가 OpenTelemetry 전역 TracerProvider를 잡기 때문에
한 프로세스 안에서 켜고 끄면 상태가 섞인다).

  off         키 없음 — 계측 코드는 있지만 no-op (기준선)
  flush_each  요청마다 client.flush() — 09-10 최초 구현
  batch       SDK 백그라운드 배치, 종료 시 한 번 flush
  down_each   Langfuse 서버가 죽은 상황(닫힌 포트) + 요청마다 flush
  down_batch  Langfuse 서버가 죽은 상황 + 배치

측정:
  ① 요청당 벽시계 지연(supervisor.handle 바깥에서 perf_counter) — 중앙값·p95
  ② 정확성 불변 — 모드와 무관하게 e2e 결과가 같은가(계측이 동작을 바꾸면 안 된다)
  ③ 유실 — 자체 트레이서 기준 기대 span 수 vs Langfuse에 실제 도착한 span 수(v2 observations API)
  ④ 장애 — 서버가 죽어도 요청이 전부 성공하는가, 지연이 얼마나 느는가

사용:
    python tools/bench_langfuse.py            # 전체 → tools/bench_langfuse_result.json
    python tools/bench_langfuse.py --rounds 5
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "bench_langfuse_result.json"
DEAD_HOST = "http://127.0.0.1:3999"  # 아무것도 안 듣는 포트 = 서버 다운 재현

MODES = {
    "off":        {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""},
    "flush_each": {"LANGFUSE_FLUSH_EACH": "1"},
    "batch":      {"LANGFUSE_FLUSH_EACH": "0"},
    "down_each":  {"LANGFUSE_FLUSH_EACH": "1", "LANGFUSE_HOST": DEAD_HOST},
    "down_batch": {"LANGFUSE_FLUSH_EACH": "0", "LANGFUSE_HOST": DEAD_HOST},
}


# ---------------------------------------------------------------- 자식 프로세스(한 모드 실행)
def _child(mode: str, rounds: int) -> None:
    sys.path.insert(0, str(ROOT))
    from app import db, langfuse_trace
    from app.eval.run_eval import _build_supervisor, _stub_sql, _suite, evaluate_task
    from app.retrieval import make_grounding_retriever

    db.build_db()
    kn, tau = make_grounding_retriever("tfidf")
    sup = _build_supervisor(_stub_sql, knowledge_retriever=kn, grounding_tau=tau)
    tasks = _suite("all")

    # 워밍업 1회(임포트·첫 연결 비용 제외)
    sup.handle(tasks[0].question, image_path=tasks[0].image_path)
    if langfuse_trace.enabled():
        langfuse_trace.flush()

    t_start = datetime.now(timezone.utc).isoformat()
    lat, e2e, errors, expected_spans = [], [], 0, 0
    for _ in range(rounds):
        for t in tasks:
            t0 = time.perf_counter()
            try:
                c = evaluate_task(sup, t)
                e2e.append(c.e2e_success)
                expected_spans += 1 + len(c.route_pred)  # 루트 span + 에이전트 step span
            except Exception:
                errors += 1
                e2e.append(None)
            lat.append((time.perf_counter() - t0) * 1000)
    t_end_loop = time.perf_counter()
    langfuse_trace.flush()
    final_flush_ms = (time.perf_counter() - t_end_loop) * 1000

    print(json.dumps({
        "mode": mode, "n": len(lat), "errors": errors, "enabled": langfuse_trace.enabled(),
        "t_start": t_start, "lat_ms": lat, "e2e": e2e,
        "expected_spans": expected_spans, "final_flush_ms": final_flush_ms,
    }))


# ---------------------------------------------------------------- Langfuse 도착 확인
def _auth() -> str:
    env = {}
    for line in open(ROOT / ".env", encoding="utf-8"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v
    return base64.b64encode(f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}".encode()).decode()


def _count_arrived(t_start: str, t_end: str) -> dict:
    """[t_start, t_end] 구간에 도착한 observation 수(이름별). 커서로 전 페이지 순회."""
    counts: dict[str, int] = {}
    cursor = None
    while True:
        q = {"fromStartTime": t_start, "toStartTime": t_end, "limit": "1000"}
        if cursor:
            q["cursor"] = cursor
        url = "http://localhost:3000/api/public/v2/observations?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + _auth()})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        for o in d.get("data", []):
            counts[o.get("name")] = counts.get(o.get("name"), 0) + 1
        cursor = (d.get("meta") or {}).get("cursor")
        if not cursor or not d.get("data"):
            break
    return counts


def _pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


# ---------------------------------------------------------------- 부모(오케스트레이션)
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--child", default=None)
    args = ap.parse_args()
    if args.child:
        _child(args.child, args.rounds)
        return

    results = {}
    for mode, env_over in MODES.items():
        env = {**os.environ, **env_over, "PYTHONIOENCODING": "utf-8", "TRACE_ECHO": "0"}
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, __file__, "--child", mode, "--rounds", str(args.rounds)],
                           env=env, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        wall = time.perf_counter() - t0
        line = [l for l in p.stdout.strip().splitlines() if l.startswith("{")]
        if p.returncode != 0 or not line:
            results[mode] = {"crashed": True, "returncode": p.returncode, "stderr": p.stderr[-800:]}
            print(f"[{mode}] CRASH rc={p.returncode}\n{p.stderr[-800:]}")
            continue
        r = json.loads(line[-1])
        r["t_end"] = datetime.now(timezone.utc).isoformat()
        r["process_wall_s"] = round(wall, 2)
        results[mode] = r
        print(f"[{mode}] n={r['n']} err={r['errors']} med={statistics.median(r['lat_ms']):.2f}ms "
              f"p95={_pct(r['lat_ms'], 95):.2f}ms final_flush={r['final_flush_ms']:.0f}ms wall={wall:.1f}s")

    # 도착 확인 — 워커가 ClickHouse에 쓰기까지 비동기라 값이 안정될 때까지 폴링
    for mode in ("flush_each", "batch"):
        r = results.get(mode)
        if not r or r.get("crashed"):
            continue
        prev, arrived = None, {}
        for _ in range(24):
            time.sleep(5)
            try:
                arrived = _count_arrived(r["t_start"], r["t_end"])
            except urllib.error.URLError as e:
                arrived = {"error": str(e)}
                break
            total = sum(arrived.values())
            if total == prev and total >= r["expected_spans"]:
                break
            prev = total
        r["arrived_by_name"] = arrived
        r["arrived_total"] = sum(v for v in arrived.values() if isinstance(v, int))
        print(f"[{mode}] expected spans={r['expected_spans']} arrived={r['arrived_total']} {arrived}")

    # 요약
    base = results.get("off", {})
    summary = {}
    for mode, r in results.items():
        if r.get("crashed"):
            summary[mode] = {"crashed": True}
            continue
        med = statistics.median(r["lat_ms"])
        summary[mode] = {
            "n": r["n"], "errors": r["errors"],
            "median_ms": round(med, 3), "p95_ms": round(_pct(r["lat_ms"], 95), 3),
            "mean_ms": round(statistics.mean(r["lat_ms"]), 3),
            "final_flush_ms": round(r["final_flush_ms"], 1),
            "e2e_same_as_off": r["e2e"] == base.get("e2e"),
            "e2e_rate": round(sum(1 for x in r["e2e"] if x) / len(r["e2e"]), 3),
            "expected_spans": r.get("expected_spans"),
            "arrived_total": r.get("arrived_total"),
        }
        if base and mode != "off":
            summary[mode]["median_overhead_ms"] = round(med - statistics.median(base["lat_ms"]), 3)

    out = {"measured_at": datetime.now().isoformat(timespec="seconds"), "rounds": args.rounds,
           "summary": summary, "raw": results}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
