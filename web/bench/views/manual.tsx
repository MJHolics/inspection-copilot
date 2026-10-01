// 자동 생성(tools/contract/sync_views.py) — 직접 고치지 말 것. 렌더 코드는 src/views/ResultView.tsx와 동일
// 전략 B: 손으로 쓴 타입
import type { InspectResponse, RouterName } from "../manual-types";

const ROUTER_LABEL: Record<RouterName, string> = {
  rule: "규칙 라우터",
  llm: "LLM 라우터",
  "llm->rule": "LLM 실패 → 규칙 폴백",
};

export function ResultView({ data }: { data: InspectResponse }) {
  return (
    <section>
      <header>
        <span className="badge">{ROUTER_LABEL[data.router]}</span>
        <span className="route">{data.route.join(" → ")}</span>
        <span className="latency">{data.latency_ms === null ? "—" : `${data.latency_ms} ms`}</span>
        {data.needs_human && <span className="warn">사람 검토 필요</span>}
      </header>
      <ol>
        {data.agents.map((a) => (
          <li key={a.agent}>
            <b>{a.agent}</b> 신뢰도 {a.confidence.toFixed(2)} {a.ok ? "✓" : "✗"}
            <p>{a.summary}</p>
            <ul>
              {a.evidence.map((e, i) => (
                <li key={i}>
                  {e.source} — {e.detail}
                  {e.score !== null && ` (${e.score.toFixed(3)})`}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      {data.report_markdown !== null && <pre className="report" style={{ whiteSpace: "pre-wrap" }}>{data.report_markdown}</pre>}
    </section>
  );
}
