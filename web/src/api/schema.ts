// 런타임 검증(zod) — 프론트가 기대하는 응답 모양. 타입은 빌드 시점에만 존재하므로,
// 백엔드가 프론트 재빌드 없이 먼저 배포되면(버전 불일치) 이 검증만이 실행 중에 어긋남을 잡는다.
import { z } from "zod";

export const EvidenceSchema = z.object({
  source: z.string(),
  detail: z.string(),
  score: z.number().nullable(),
});

export const AgentOutSchema = z.object({
  agent: z.enum(["vision", "analytics", "knowledge", "report"]),
  ok: z.boolean(),
  summary: z.string(),
  confidence: z.number(),
  needs_human: z.boolean(),
  evidence: z.array(EvidenceSchema),
});

export const InspectResponseSchema = z.object({
  answer: z.string(),
  ok: z.boolean(),
  needs_human: z.boolean(),
  route: z.array(z.enum(["vision", "analytics", "knowledge", "report"])),
  router: z.enum(["rule", "llm", "llm->rule"]),
  reason: z.string(),
  grounding_retriever: z.string(),
  agents: z.array(AgentOutSchema),
  report_markdown: z.string().nullable(),
  latency_ms: z.number().int().nullable(),
});
