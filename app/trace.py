"""멀티에이전트 관측성 — 요청별로 라우팅 경로·에이전트 단계·지연·사람검토를 구조화 로깅.

각 요청을 한 줄 JSON(JSONL)으로 남긴다: 어떤 경로로 라우팅됐는지(route), 각 서브에이전트
단계의 성공·신뢰도·지연, 전체 지연, 사람검토 필요 여부. `summarize()`는 성공률·사람검토율·
평균 단계수·라우팅 분포·지연 분위수를 뽑는 순수 함수라 네트워크 없이 단위테스트된다.

`nl2sql-analytics-agent/app/trace.py`의 단일호출 트레이싱 패턴을 멀티에이전트(요청 1건 =
여러 에이전트 단계)로 확장한 것.

설정(환경변수):
  TRACE_FILE   기록할 JSONL 경로(비우면 파일 기록 안 함, stdout만). 예: traces/trace.jsonl
  TRACE_ECHO   "0"이면 stdout 출력 끔(기본 켜짐 — 서버 로그에 남도록).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class StepRecord:
    """한 서브에이전트 호출 단계."""

    agent: str
    ok: bool
    latency_ms: int
    confidence: float = 1.0
    needs_human: bool = False
    error: str | None = None


@dataclass
class RequestTrace:
    """요청 1건의 전체 트레이스(라우팅 + 단계들 + 집계)."""

    ts: str
    request: str
    router: str
    route: list[str]
    steps: list[StepRecord] = field(default_factory=list)
    total_latency_ms: int = 0
    ok: bool = True
    needs_human: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Tracer:
    """RequestTrace를 JSONL 한 줄로 기록. 파일 경로/stdout 출력은 환경변수로 제어."""

    def __init__(self, path: str | None = None, echo: bool | None = None) -> None:
        self.path = os.getenv("TRACE_FILE", "") if path is None else path
        self.echo = (os.getenv("TRACE_ECHO", "1") != "0") if echo is None else echo

    def emit(self, trace: RequestTrace) -> None:
        line = json.dumps(trace.to_dict(), ensure_ascii=False)
        if self.echo:
            print("[trace] " + line, flush=True)
        if self.path:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def _percentile(values: list[int], p: float) -> int:
    """nearest-rank 근사 분위수. values는 비어있지 않다고 가정."""
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return s[i]


def summarize(records: list[dict]) -> dict:
    """트레이스 레코드 목록 → 운영 지표(순수 함수).

    멀티에이전트 특유 지표: 라우팅 경로 분포(어느 에이전트 조합이 얼마나), 평균 단계수,
    사람검토율(가드레일 발동 빈도) — eval/관측성 서사의 핵심 수치.
    """
    n = len(records)
    if n == 0:
        return {"count": 0}
    lat = [int(r.get("total_latency_ms", 0)) for r in records]
    oks = sum(1 for r in records if r.get("ok"))
    humans = sum(1 for r in records if r.get("needs_human"))
    steps_per = [len(r.get("steps", [])) for r in records]
    route_dist: dict[str, int] = {}
    for r in records:
        key = ">".join(r.get("route", []))
        route_dist[key] = route_dist.get(key, 0) + 1
    return {
        "count": n,
        "success_rate": round(oks / n, 3),
        "human_review_rate": round(humans / n, 3),
        "avg_steps": round(sum(steps_per) / n, 2),
        "route_distribution": dict(sorted(route_dist.items(), key=lambda kv: -kv[1])),
        "latency_ms_p50": _percentile(lat, 50),
        "latency_ms_p95": _percentile(lat, 95),
    }


def render_html(summary: dict, records: list[dict]) -> str:
    """멀티에이전트 운영 대시보드(순수 함수, 무의존). 요청 트레이스 → 한 페이지.

    플랫폼의 '운영' 기둥을 시각화한다: 라우팅 분포(어느 에이전트 조합이 얼마나),
    사람검토(게이트 정지)율, 지연 분위수, 최근 요청. Cloud Monitoring의 무료 등가물.
    """
    import html as _html

    def esc(v: object) -> str:
        return _html.escape(str(v))

    cards = [
        ("요청 수", summary.get("count", 0)),
        ("성공률", f"{summary.get('success_rate', 0):.0%}"),
        ("사람검토율(게이트)", f"{summary.get('human_review_rate', 0):.0%}"),
        ("평균 단계수", summary.get("avg_steps", 0)),
        ("지연 p50", f"{summary.get('latency_ms_p50', 0)} ms"),
        ("지연 p95", f"{summary.get('latency_ms_p95', 0)} ms"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
        for k, v in cards
    )
    dist = summary.get("route_distribution", {})
    mx = max(dist.values()) if dist else 1
    dist_html = "".join(
        f'<div class="bar"><span class="lbl">{esc(route or "(빈 경로)")}</span>'
        f'<span class="track"><span class="fill" style="width:{int(100 * n / mx)}%"></span></span>'
        f'<span class="num">{esc(n)}</span></div>'
        for route, n in dist.items()
    )
    rows = []
    for r in records[-50:][::-1]:
        flag = "🛑" if r.get("needs_human") else ("✓" if r.get("ok") else "✗")
        rows.append(
            f"<tr class=\"{'human' if r.get('needs_human') else 'ok'}\">"
            f"<td>{esc(r.get('ts', ''))}</td><td>{esc(r.get('request', ''))}</td>"
            f"<td>{esc('>'.join(r.get('route', [])))}</td><td>{esc(r.get('router', ''))}</td>"
            f"<td>{esc(r.get('total_latency_ms', 0))}</td><td>{flag}</td></tr>"
        )
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>InspectOps — 운영 대시보드</title>
<style>
 body{{font-family:system-ui,'Malgun Gothic',sans-serif;margin:24px;color:#16213e}}
 h1{{font-size:20px}} h2{{font-size:15px;color:#444;margin-top:24px}}
 .cards{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
 .card{{background:#eef2fb;border-radius:10px;padding:14px 18px;min-width:120px}}
 .card .v{{font-size:22px;font-weight:700}} .card .k{{font-size:12px;color:#555}}
 .bar{{display:flex;align-items:center;gap:10px;margin:4px 0;font-size:13px}}
 .bar .lbl{{width:230px;text-align:right;color:#333}} .bar .num{{width:30px}}
 .track{{flex:1;background:#eee;border-radius:6px;height:14px}}
 .fill{{display:block;height:14px;background:#3b5bdb;border-radius:6px}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
 th,td{{border-bottom:1px solid #eee;padding:6px 8px;text-align:left;max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
 tr.human td{{background:#fff6e6}} th{{background:#fafafa}}
</style>
<h1>🏭🩺 InspectOps — 멀티에이전트 운영 지표</h1>
<div class="cards">{card_html}</div>
<h2>라우팅 분포(에이전트 조합)</h2>{dist_html}
<h2>최근 요청</h2>
<table><thead><tr><th>시각</th><th>요청</th><th>라우팅</th><th>라우터</th><th>지연ms</th><th>게이트</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</html>"""


def load_traces(path: str) -> list[dict]:
    """JSONL 파일을 레코드 리스트로 읽는다."""
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line:
                out.append(json.loads(line))
    return out


def _main() -> None:
    """python -m app.trace [경로] [--html [출력.html]] → 요약 지표 / HTML 운영 대시보드."""
    import sys

    args = [a for a in sys.argv[1:] if a != "--html"]
    want_html = "--html" in sys.argv
    path = args[0] if args else os.getenv("TRACE_FILE", "traces/trace.jsonl")
    if not os.path.exists(path):
        print(f"트레이스 파일이 없습니다: {path}")
        return
    records = load_traces(path)
    summary = summarize(records)
    if want_html:
        out = args[1] if len(args) > 1 else "traces/dashboard.html"
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_html(summary, records))
        print(f"대시보드 생성: {out}  (요청 {summary.get('count', 0)}건)")
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
