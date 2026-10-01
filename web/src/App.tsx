import { useState } from "react";
import { ContractError, inspect } from "./api/client";
import type { InspectResponse } from "./api/types";
import { ResultView } from "./views/ResultView";

export function App() {
  const [q, setQ] = useState("라인별 불량 현황 정리해서 주간 보고서로 만들어줘");
  const [data, setData] = useState<InspectResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      setData(await inspect(q));
    } catch (e) {
      setData(null);
      setErr(e instanceof ContractError ? `응답 계약 불일치: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 860, margin: "24px auto", fontFamily: "system-ui, sans-serif" }}>
      <h1>Inspection Copilot 콘솔</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <input value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "75%" }} />
        <button disabled={busy}>{busy ? "처리 중…" : "질의"}</button>
      </form>
      {err && <p role="alert">{err}</p>}
      {data && <ResultView data={data} />}
    </main>
  );
}
