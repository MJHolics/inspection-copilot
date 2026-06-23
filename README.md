# Inspection Copilot — 멀티에이전트 품질 검사 코파일럿

[![ci](https://github.com/MJHolics/inspection-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/MJHolics/inspection-copilot/actions/workflows/ci.yml)

> 제조/의료 검사 현장을 위한 **검증 가능한 멀티에이전트 시스템**. 검사자가 자연어로 묻거나
> 이미지를 올리면, supervisor 에이전트가 의도를 파악해 전문 에이전트(비전·분석·지식·리포트)로
> **동적 라우팅**하고 근거와 함께 답한다.

설계 배경·단계 계획은 [PLAN.md](PLAN.md), 배포는 [DEPLOY.md](DEPLOY.md) 참조.

## 아키텍처

```
   사용자(검사 엔지니어): 자연어 질문 / 이미지 업로드
                     │
          ┌──────────▼──────────┐
          │  Supervisor (동적 라우터) │  의도 파악 → 경로 결정(고정 체인 ❌) → 종합
          └──┬─────┬─────┬─────┬──┘
             ▼     ▼     ▼     ▼
        Vision  Analytics Knowledge Report
        ONNX CNN  NL2SQL   RAG       종합·PDF
        +conformal +dry-run +근거    +신뢰도
        /OOD게이트  +자기수정 거리게이트  배지
             │     │     │     │
             └──── 트레이싱 · Eval 하네스 · 가드레일(cross-cutting) ────┘
              요청별 JSONL    라우팅·그라운딩·   "모를 때 멈춤"
                            게이트·e2e 수치화   (needs_human)
```

## 실행 (P1)

```bash
python cli.py "스크래치 결함은 어떤 절차로 처리해야 해?"        # → knowledge
python cli.py "라인별 불량 건수 많은 순으로 알려줘"             # → analytics (실 NL2SQL)
python cli.py "이 사진 불량 보고 추세 통계로 보고서 만들어줘" --image x.jpg
#   → vision → analytics → report (요청에 따라 경로가 달라지는 동적 라우팅)

python -m pytest -q          # 오프라인 단위테스트(LLM·네트워크 불필요)
python -m app.trace traces/trace.jsonl   # 트레이스 요약 지표
python -m app.eval.run_eval  # 골든셋 평가 지표(라우팅·그라운딩·게이트·e2e)

python demo.py                                      # gradio 데모 → localhost:7860
uvicorn app.server:app --port 8000                 # FastAPI 서빙(/health /inspect /eval)
```

서빙·데모·배포는 [DEPLOY.md](DEPLOY.md) 참조(로컬·HF Spaces·Docker).

> **Analytics** 에이전트는 합성 검사 DB(SQLite, `app/db.py`가 시드 고정으로 결정적 생성)에 대해
> **자연어 → SQL 생성 → SELECT 전용 가드레일 → dry-run 검증 → (실패 시 1회 자기수정) → 실행 →
> 요약**을 수행한다. SQL 생성에는 LLM 키(Gemini 무료 등)가 필요하며, 키가 없으면 안전하게
> 사람검토로 멈춘다(라우팅·트레이싱은 그대로 동작).
>
> **Knowledge** 에이전트는 검사 SOP 문서(`app/docs/sop/`)를 **TF-IDF 코사인으로 검색 →
> 근거 거리 게이트 → 그라운딩 답(출처 인용)**으로 답한다. 관련 근거가 약하면 환각 대신
> 사람검토로 멈춘다. 검색기는 주입 가능(베이스라인 TF-IDF → BGE-M3/Chroma 벡터로 교체),
> 답 생성은 LLM 주입 시 요약, 없으면 추출형으로 동작한다.
>
> **Report** 에이전트는 앞 단계 결과를 **구조화 리포트(요약·발견·권고·종합신뢰도·사람검토
> 배지)**로 합친다. 종합 신뢰도는 관여 에이전트 신뢰도의 최솟값(가장 약한 고리), 사람검토는
> OR로 전파한다. 기본은 markdown, reportlab이 있으면 한글 PDF도 생성(없으면 markdown 폴백).
>
> **Vision** 에이전트는 **실 엣지 CNN(MobileNetV3-Small, ONNX 6MB, `app/models/`)**으로 결함을
> 분류하고, 그 확률에 **trust 게이트**(conformal 예측집합 + 신뢰도/OOD)를 적용한다(`app/trust.py`,
> `vlm-defect-inspector`의 conformal LAC/APS·OOD 방법론 순수 포팅). 신뢰도가 게이트(0.8) 미만이거나
> 예측집합이 단일로 좁혀지지 않으면 **환각 대신 사람검토로 멈춘다**. 모델은 torch 없이 onnxruntime로
> CPU 수 ms 추론(`samples/`의 NEU 예시로 데모). 모델·의존성이 없으면 안전 멈춤으로 폴백하고,
> trust 층 자체는 순수·오프라인 테스트된다.

요청마다 supervisor가 의도를 파악해 서로 다른 에이전트 조합·순서로 라우팅하고(고정 체인 ❌),
각 단계를 트레이싱하며, 어느 에이전트든 신뢰도가 낮으면 전체를 사람검토로 멈춘다.

## 한 줄 요약

"동작하는 에이전트"가 아니라 **측정·검증되는 에이전트**:
- **멀티에이전트 오케스트레이션**(LangGraph supervisor, 동적 tool-calling 라우팅)
- **비전 검사**(엣지 CNN ONNX + 신뢰도/OOD/conformal 게이트)
- **데이터 분석**(NL2SQL, dry-run 검증)
- **지식 그라운딩**(RAG, 근거 거리 게이트)
- **Eval 하네스**(라우팅 정확도·그라운딩 충실도·end-to-end 성공률)
- **관측성**(요청별 트레이싱·지표) + **가드레일**(모를 때 멈춤)

## Eval — "측정되는 에이전트"

큐레이션 골든셋(`app/eval/tasks.py`, 15 태스크)에 시스템을 돌려 4개 지표를 **재현 가능하게**
수치화한다. 라우팅·그라운딩·게이트는 완전 오프라인, Analytics는 SQL 생성만 결정적 스텁으로
주입해 **실 DB 실행 파이프라인**(가드레일·dry-run·실행·요약)을 측정한다(LLM 'SQL 품질'이 아니라
시스템 동작을 측정 — 키 불요·결정적). 회귀가 나면 이 수치가 떨어져 잡힌다.

| 지표 | 값 | 의미 |
|---|---|---|
| routing_exact_acc | **1.00** | 기대 라우트(에이전트·순서) 정확 일치 |
| grounding_acc | **1.00** | Knowledge가 기대 SOP 출처에 그라운딩 |
| gate_acc | **1.00** | needs_human(근거 부족 시 멈춤)이 기대와 일치 |
| e2e_success_rate | **1.00** | 라우팅+그라운딩+게이트+실행 모두 성공 |

`python -m app.eval.run_eval`로 재현. (현재 골든셋 15건 기준 — 실패 케이스를 추가하면 회귀 탐지력↑)

## 상태

| Phase | 내용 | 상태 |
|---|---|---|
| P0 | 레포 골격 + 설계문서 | ✅ |
| P1 | Supervisor 동적 라우터 + 서브에이전트 스텁(인터페이스 고정) + 트레이싱 | ✅ |
| P2 | 서브에이전트 실구현 — **Analytics ✅ · Knowledge ✅ · Report ✅ · Vision ✅** | ✅ |
| P3 | Eval 하네스(라우팅·그라운딩·게이트·e2e) + 가드레일 | ✅ |
| P4 | 서빙(FastAPI) + 데모(gradio) + Docker ✅ · HF Spaces 배포(사용자 push 대기) | 🔄 |
