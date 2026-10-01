// 앱이 쓰는 타입의 단일 출처 — OpenAPI에서 생성한 타입(generated.ts)을 이름만 붙여 다시 내보낸다.
// 백엔드 응답 모델이 바뀌면 `npm run gen:types` 후 `tsc`가 어긋난 사용처를 빌드에서 잡는다.
import type { components } from "./generated";

export type InspectResponse = components["schemas"]["InspectResponse"];
export type AgentOut = components["schemas"]["AgentOut"];
export type InspectRequest = components["schemas"]["InspectRequest"];
export type RouterName = InspectResponse["router"];
