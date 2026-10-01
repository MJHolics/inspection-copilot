import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { InspectResponseSchema } from "../src/api/schema";
import { buildInspectBody } from "../src/api/client";
import { ResultView } from "../src/views/ResultView";
import type { InspectResponse } from "../src/api/types";

const sample = JSON.parse(readFileSync(new URL("./fixtures/inspect_sample.json", import.meta.url), "utf-8"));

test("실제 백엔드 응답이 zod 계약을 통과한다", () => {
  assert.equal(InspectResponseSchema.safeParse(sample).success, true);
});

test("화면이 라우터 라벨·경로·신뢰도를 그린다", () => {
  const html = renderToStaticMarkup(<ResultView data={sample as InspectResponse} />);
  assert.match(html, /규칙 라우터|LLM 라우터|LLM 실패/);
  assert.match(html, /신뢰도 \d\.\d\d/);
  assert.doesNotMatch(html, /undefined|NaN/);
});

test("필드 이름이 바뀐 응답은 화면 전에 거부된다(M1)", () => {
  const mutated = structuredClone(sample);
  for (const a of mutated.agents) {
    a.trust_score = a.confidence;
    delete a.confidence;
  }
  const r = InspectResponseSchema.safeParse(mutated);
  assert.equal(r.success, false);
});

test("요청 본문은 생성된 요청 타입을 따른다", () => {
  assert.deepEqual(buildInspectBody("q"), { question: "q", image_path: null });
});
