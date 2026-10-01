"""온프레미스 라우터 벤치 — 외부 API 없이(로컬 vLLM) LLM 라우터가 규칙 라우터 대비 얼마나 맞히나.

폐쇄망에서는 Gemini/OpenAI를 못 쓴다. 그러면 에이전트의 '두뇌'를 사내 GPU의 소형 모델로 바꿔야 하는데,
그때 무엇을 잃는지(정확도·파싱 실패·지연)를 같은 태스크셋(골든 15 + 적대적 13 + held-out 40)으로 잰다.
골든·적대적은 규칙 라우터에 in-sample이므로 공정 비교는 held-out으로 한다.

사용: LOCAL_LLM_BASE_URL=http://localhost:8000/v1 LOCAL_LLM_MODEL=<서빙 중 모델> \
      python tools/onprem/bench_local_router.py --tag qwen1.5b --repeats 2
결과: results/onprem/router_<tag>.json (케이스별 예측·지연 + 집계)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.agents import AgentRequest, KnowledgeAgent, ReportAgent, VisionAgent  # noqa: E402
from app.agents.analytics import AnalyticsAgent  # noqa: E402
from app.eval.adversarial_tasks import ADVERSARIAL  # noqa: E402
from app.eval.metrics import route_exact, route_jaccard  # noqa: E402
from app.eval.heldout_route_tasks import HELDOUT  # noqa: E402
from app.eval.tasks import GOLDEN  # noqa: E402
from app.router import LLMRouter, RuleRouter  # noqa: E402


def agents():
    return {"vision": VisionAgent(), "analytics": AnalyticsAgent(sql_llm=lambda s, u: ""),
            "knowledge": KnowledgeAgent(), "report": ReportAgent()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--rule-only", action="store_true")
    a = ap.parse_args()

    ag = agents()
    tasks = ([("golden", t) for t in GOLDEN] + [("adversarial", t) for t in ADVERSARIAL]
             + [("heldout", t) for t in HELDOUT])

    if a.rule_only:
        router, raw_call = RuleRouter(), None
    else:
        from app.llm import LLM
        assert config.LOCAL_LLM_BASE_URL, "LOCAL_LLM_BASE_URL 필요"
        client = LLM()
        assert client.provider == "local", client.provider
        raw_call = lambda s, u: client.complete(s, u, temperature=0.0)  # noqa: E731
        router = LLMRouter(complete=raw_call)

    runs = []
    for rep in range(a.repeats):
        cases = []
        for split, t in tasks:
            req = AgentRequest(text=t.question, image_path=t.image_path)
            parse_ok = None
            t0 = time.perf_counter()
            plan = router.plan(req, ag)
            ms = (time.perf_counter() - t0) * 1000
            if raw_call is not None:
                # 폴백 여부는 plan.router로 판정(llm->rule이면 LLM 출력을 못 썼다)
                parse_ok = plan.router == "llm"
            cases.append({
                "id": t.id, "split": split, "pred": plan.steps, "gold": t.expected_route,
                "exact": route_exact(plan.steps, t.expected_route),
                "jaccard": round(route_jaccard(plan.steps, t.expected_route), 3),
                "router": plan.router, "llm_used": parse_ok, "ms": round(ms, 1),
            })
        runs.append(cases)

    def agg(cases, split=None):
        cs = [c for c in cases if split is None or c["split"] == split]
        out = {"n": len(cs), "exact": round(sum(c["exact"] for c in cs) / len(cs), 3),
               "jaccard": round(statistics.mean(c["jaccard"] for c in cs), 3)}
        if raw_call is not None:
            out["fallback_rate"] = round(sum(not c["llm_used"] for c in cs) / len(cs), 3)
            ms = sorted(c["ms"] for c in cs)
            out["p50_ms"] = ms[len(ms) // 2]
            out["p95_ms"] = ms[min(len(ms) - 1, int(len(ms) * 0.95))]
        return out

    flips = 0
    if len(runs) > 1:
        flips = sum(r0["pred"] != r1["pred"] for r0, r1 in zip(runs[0], runs[-1]))

    summary = {
        "tag": a.tag, "model": None if a.rule_only else config.LLM_MODEL["local"],
        "base_url": None if a.rule_only else config.LOCAL_LLM_BASE_URL,
        "all": agg(runs[0]), "golden": agg(runs[0], "golden"),
        "adversarial": agg(runs[0], "adversarial"), "heldout": agg(runs[0], "heldout"),
        "repeat_flips": flips, "repeats": a.repeats,
    }
    outdir = ROOT / "results" / "onprem"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"router_{a.tag}.json").write_text(
        json.dumps({"summary": summary, "runs": runs}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
