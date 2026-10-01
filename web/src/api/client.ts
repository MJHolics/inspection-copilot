import type { InspectRequest, InspectResponse } from "./types";
import { InspectResponseSchema } from "./schema";

export class ContractError extends Error {}

export function buildInspectBody(question: string, imagePath?: string): InspectRequest {
  return { question, image_path: imagePath ?? null };
}

/** POST /inspect. 응답은 zod로 검증한다 — 어긋나면 화면을 그리지 않고 ContractError를 던진다. */
export async function inspect(question: string, imagePath?: string, base = "/api"): Promise<InspectResponse> {
  const r = await fetch(`${base}/inspect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildInspectBody(question, imagePath)),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const parsed = InspectResponseSchema.safeParse(await r.json());
  if (!parsed.success) throw new ContractError(parsed.error.issues.map((i) => i.path.join(".")).join(", "));
  return parsed.data;
}
