// 전략 B — 손으로 쓴 타입. 작성 시점(10-01) 응답을 보고 옮겨 적었다. 백엔드와 연결돼 있지 않아
// 백엔드가 바뀌어도 이 파일은 그대로다(현실에서 흔한 상태).
export type RouterName = "rule" | "llm" | "llm->rule";
export interface Evidence { source: string; detail: string; score: number | null }
export interface AgentOut {
  agent: "vision" | "analytics" | "knowledge" | "report";
  ok: boolean; summary: string; confidence: number; needs_human: boolean; evidence: Evidence[];
}
export interface InspectResponse {
  answer: string; ok: boolean; needs_human: boolean; route: AgentOut["agent"][]; router: RouterName;
  reason: string; grounding_retriever: string; agents: AgentOut[]; report_markdown: string | null; latency_ms: number | null;
}
