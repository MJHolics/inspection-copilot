# Inspection Copilot — 멀티에이전트 품질 검사 코파일럿

[![ci](https://github.com/MJHolics/inspection-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/MJHolics/inspection-copilot/actions/workflows/ci.yml)

> 제조/의료 검사 현장을 위한 **검증 가능한 멀티에이전트 시스템**. 검사자가 자연어로 묻거나
> 이미지를 올리면, supervisor 에이전트가 의도를 파악해 전문 에이전트(비전·분석·지식·리포트)로
> **동적 라우팅**하고 근거와 함께 답한다.

🚧 **개발 중** — 설계와 단계 계획은 [PLAN.md](PLAN.md) 참조.

## 실행 (P1)

```bash
python cli.py "스크래치 결함은 어떤 절차로 처리해야 해?"        # → knowledge
python cli.py "이번 달 스크래치 불량 몇 건이야?"                 # → analytics
python cli.py "이 사진 불량 보고 추세 통계로 보고서 만들어줘" --image x.jpg
#   → vision → analytics → report (요청에 따라 경로가 달라지는 동적 라우팅)

python -m pytest -q          # 오프라인 단위테스트(LLM·네트워크 불필요)
python -m app.trace traces/trace.jsonl   # 트레이스 요약 지표
```

요청마다 supervisor가 의도를 파악해 서로 다른 에이전트 조합·순서로 라우팅하고(고정 체인 ❌),
각 단계를 트레이싱하며, 어느 에이전트든 신뢰도가 낮으면 전체를 사람검토로 멈춘다.

## 한 줄 요약

"동작하는 에이전트"가 아니라 **측정·검증되는 에이전트**:
- **멀티에이전트 오케스트레이션**(LangGraph supervisor, 동적 tool-calling 라우팅)
- **비전 검사**(YOLO + VLM + 신뢰도/OOD/conformal 게이트)
- **데이터 분석**(NL2SQL, dry-run 검증)
- **지식 그라운딩**(RAG, 근거 거리 게이트)
- **Eval 하네스**(라우팅 정확도·그라운딩 충실도·end-to-end 성공률)
- **관측성**(요청별 트레이싱·지표) + **가드레일**(모를 때 멈춤)

## 상태

| Phase | 내용 | 상태 |
|---|---|---|
| P0 | 레포 골격 + 설계문서 | ✅ |
| P1 | Supervisor 동적 라우터 + 서브에이전트 스텁(인터페이스 고정) + 트레이싱 | ✅ |
| P2 | 서브에이전트 실구현 | ⏳ |
| P3 | Eval 하네스 + 가드레일 | ⏳ |
| P4 | 서빙 + 데모 + 배포 | ⏳ |
