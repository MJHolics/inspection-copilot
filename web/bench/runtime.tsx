// 계약 변경 실험의 실행 단계 — 변경된 백엔드 응답을 각 전략의 화면 코드에 실제로 렌더한다.
//
//   npx tsx bench/runtime.tsx <fixtures.json>   → stdout에 JSON
//
// fixtures.json: { request_ok: bool, pairs: [{ baseline, mutated }] }
// 결과(문항별): runtime_error(렌더 중 예외) · contract_error(zod가 거부) · http_error(요청이 422) ·
//               silent(예외 없이 렌더했는데 화면이 원래와 다르다) · unaffected(화면이 원래와 같다)
// "원래 화면" = 같은 전략으로 변경 전 응답을 렌더한 결과. 모든 변경은 의미를 보존하는 변경이라
// 올바른 프론트라면 화면이 같아야 한다(대조군: 선택 필드 추가).
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { InspectResponseSchema } from "../src/api/schema";
import { ResultView as ManualView } from "./views/manual";
import { ResultView as UntypedView } from "./views/untyped";

type Outcome = "runtime_error" | "contract_error" | "http_error" | "silent" | "unaffected";
type Strategy = "untyped" | "manual" | "zod";

const render = (View: (p: { data: any }) => any, data: unknown): string =>
  renderToStaticMarkup(<View data={data} />);

function outcome(strategy: Strategy, baseline: unknown, mutated: unknown, requestOk: boolean): Outcome {
  if (!requestOk) return "http_error"; // 백엔드가 요청을 422로 거부 — 모든 전략이 화면 전에 실패한다
  const View = strategy === "untyped" ? UntypedView : ManualView;
  const expected = render(View, baseline);
  let data = mutated;
  if (strategy === "zod") {
    const p = InspectResponseSchema.safeParse(mutated);
    if (!p.success) return "contract_error";
    data = p.data;
  }
  let html: string;
  try {
    html = render(View, data);
  } catch {
    return "runtime_error";
  }
  return html === expected ? "unaffected" : "silent";
}

const fx = JSON.parse(readFileSync(process.argv[2]!, "utf-8")) as {
  request_ok: boolean;
  pairs: { baseline: unknown; mutated: unknown }[];
};
const out: Record<string, Record<Outcome, number>> = {};
const example: Record<string, string> = {};
for (const s of ["untyped", "manual", "zod"] as Strategy[]) {
  const c: Record<Outcome, number> = { runtime_error: 0, contract_error: 0, http_error: 0, silent: 0, unaffected: 0 };
  for (const p of fx.pairs) {
    const o = outcome(s, p.baseline, p.mutated, fx.request_ok);
    c[o] += 1;
    if (o === "silent" && !example[s]) {
      // 무엇이 조용히 달라졌는지 한 군데만 남긴다(보고용)
      const View = s === "untyped" ? UntypedView : ManualView;
      const a = render(View, p.baseline), b = render(View, s === "zod" ? InspectResponseSchema.parse(p.mutated) : p.mutated);
      let i = 0;
      while (i < a.length && a[i] === b[i]) i++;
      example[s] = `원래 …${a.slice(Math.max(0, i - 30), i + 40)}… / 변경 후 …${b.slice(Math.max(0, i - 30), i + 40)}…`;
    }
  }
  out[s] = c;
}
console.log(JSON.stringify({ counts: out, silent_example: example }));
