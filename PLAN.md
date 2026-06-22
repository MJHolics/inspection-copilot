# Inspection Copilot — 설계 문서 (PLAN)

> 제조/의료 검사 현장을 위한 **멀티에이전트 품질 코파일럿**. 검사자가 자연어로 묻거나 이미지를
> 올리면, supervisor 에이전트가 의도를 파악해 전문 에이전트(비전·분석·지식·리포트)로 **동적
> 라우팅**하고 근거와 함께 답한다. 핵심 차별점은 "동작하는 에이전트"가 아니라 **측정·검증되는
> 에이전트** — 라우팅 정확도·그라운딩 충실도·end-to-end 성공률을 eval로 수치화하고, 요청을
> 트레이싱하며, 각 도구에 가드레일을 건다.

## 왜 이 프로젝트인가 (포지셔닝)

- **트렌드 정렬**: 멀티에이전트 오케스트레이션·tool-use·RAG·멀티모달(VLM)·LLMOps(eval·관측성·
  가드레일) — 현재 AI 엔지니어 채용에서 가장 수요 많은 스택.
- **도메인 차별화**: 그 스택을 지원자의 강점 도메인(제조 검사 + 의료기기 신뢰성, ISO 13485 경력)에
  적용. 일반 챗봇이 아니라 "검증 가능한 산업 검사 AI".
- **기존 자산 승격**: 흩어진 토이들(단일 비전검사 에이전트, NL2SQL, RAG, VLM 결함분류)을 하나의
  일관된 대형 시스템으로 통합·심화. 기존 `vision-inspection-agent`(고정 3단계 체인)를 **동적
  멀티에이전트 + eval + 관측성 + 가드레일**로 명확히 능가한다.

## 아키텍처

```
              사용자(검사 엔지니어): 자연어 질문 / 이미지 업로드
                                  │
                      ┌───────────▼───────────┐
                      │   Supervisor (LangGraph) │  의도 파악 → 계획 → 라우팅 → 종합
                      │   tool-calling 동적 라우팅 │  (고정 체인 ❌)
                      └───┬─────┬─────┬─────┬────┘
            ┌─────────────┘     │     │     └─────────────┐
            ▼                   ▼     ▼                   ▼
   Vision Inspection      Analytics  Knowledge         Report
   (YOLO + VLM + trust)   (NL2SQL)   (RAG 그라운딩)     (구조화→PDF)
   결함 감지·해석·신뢰도   생산/검사DB  검사표준·SOP 근거   종합 리포트
            │                   │     │                   │
            └─────────── 가드레일 · 트레이싱 · Eval (cross-cutting) ──────────┘
```

### 에이전트
1. **Supervisor** — 요청을 해석해 어떤 서브에이전트(들)를 어떤 순서로 부를지 동적으로 결정.
   tool-calling 기반(각 서브에이전트를 도구로 노출). 결과를 종합해 최종 답·리포트 생성.
2. **Vision Inspection** — 이미지 → YOLO 결함 감지 + VLM(결함 유형·심각도·설명) + **trust 층**
   (confidence·OOD·conformal 게이트 → 애매하면 사람검토 플래그). `vlm-defect-inspector` 자산 재활용.
3. **Analytics (NL2SQL)** — 자연어 → 검사/생산 DB SQL 생성·**dry-run 검증**·실행·요약.
   `nl2sql-analytics-agent` 자산 재활용(SELECT 전용·비용 가드).
4. **Knowledge (RAG)** — 검사 표준·SOP·결함 처리 지침 문서를 검색해 답을 그라운딩(근거 거리 게이트).
5. **Report** — 수집 근거를 구조화 리포트(요약·발견·권고·신뢰도)로 합쳐 PDF 생성.

### Cross-cutting (이 프로젝트의 깊이)
- **Eval 하네스**: 큐레이션 태스크셋으로 ①라우팅 정확도(올바른 에이전트 선택) ②도구선택 정확도
  ③그라운딩/충실도(근거 기반 답인가) ④end-to-end 태스크 성공률을 수치화. "동작" 너머 "측정".
- **관측성/트레이싱**: 요청별로 에이전트 그래프 경로·도구 호출·지연·토큰/비용을 구조화 로깅 →
  지표 집계(성공률·p50/p95 지연·라우팅 분포).
- **가드레일/Trust**: 비전(conformal/OOD), NL2SQL(SELECT 전용·dry-run), RAG(그라운딩 거리) →
  "검증 가능한 에이전트". 모를 때 멈추고 사람검토로 라우팅.

## LLM 제공자
provider 무관 클라이언트. **Gemini 무료 티어 기본**(사용자 API키 사정), Anthropic/OpenAI 옵션.
`nl2sql-analytics-agent/app/llm.py` 패턴 재사용.

## 단계 (phase)
- **P0** 레포 골격 + 본 설계문서. (현재)
- **P1** Supervisor 동적 라우터 + 4개 서브에이전트 스텁(인터페이스 고정) + 트레이싱 배선.
- **P2** 서브에이전트 실구현(기존 자산 재활용·승격).
- **P3** Eval 하네스 + 가드레일 + 실측 수치.
- **P4** 서빙(FastAPI) + 데모 UI + Docker + HF Spaces 배포 + README(SOTA 서사).

## 재활용 자산 맵
| 새 컴포넌트 | 출처 |
|---|---|
| Vision agent | `vlm-defect-inspector`(VLM·confidence·OOD·conformal), `vision-inspection-agent`(YOLO·PDF) |
| Analytics agent | `nl2sql-analytics-agent`(NL2SQL·dry-run·트레이싱) |
| Knowledge agent | `multimodal_rag`(BGE-M3·Chroma·hybrid·Hit Rate/MRR) |
| 트레이싱 | `nl2sql-analytics-agent/app/trace.py` 패턴 |

## 열린 결정(사용자 확인 가능)
- 레포 이름: `inspection-copilot` (가칭) — 변경 가능.
- 도메인 1차 초점: 제조 검사 우선(의료는 확장). 
- 데이터: 검사 DB는 합성/공개셋(예: NEU 결함 로그를 SQLite로) — P2에서 확정.
