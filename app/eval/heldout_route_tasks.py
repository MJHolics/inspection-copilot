"""Held-out 라우팅 셋 — 규칙 라우터 튜닝에도, LLM 라우터 프롬프트 작성에도 쓰지 않은 질의.

골든(15)·적대적(13) 셋은 규칙 라우터를 고치는 데 쓰였으므로 규칙 라우터에 in-sample이다
(2026-09-26 측정: 규칙 라우터 28/28). 온프레미스 LLM 라우터와 공정하게 비교하려면 둘 다 처음 보는
질의가 필요해, **어느 라우터도 돌리기 전에** 라벨을 먼저 고정했다(2026-09-26).

라벨 규약(`tasks.py`와 동일):
  • 필요한 에이전트만 · 순서는 vision → analytics → knowledge → report
  • report는 사용자가 보고서/문서화를 명시했거나 실질 에이전트가 2개 이상일 때만
  • 검사와 무관한 질문은 ["knowledge"](근거 게이트가 멈추는 경로)
  • 이미지가 있으면 vision 포함
표현 축: 구어체·동의어·영어·오타·키워드 없는 의도·복합 요청.
"""
from __future__ import annotations

from .tasks import Task

IMG = "samples/x.jpg"
K, A, V, R = "knowledge", "analytics", "vision", "report"

HELDOUT: list[Task] = [
    # ── knowledge: 절차·기준·원인 (동의어/구어체) ─────────────────────────────
    Task("h-k01", "긁힌 자국 생기면 현장에서 뭐부터 해야 돼?", [K]),
    Task("h-k02", "표면이 거북등처럼 갈라진 건 어떻게 처리하나요", [K]),
    Task("h-k03", "이물 박힌 제품은 폐기야 재작업이야?", [K]),
    Task("h-k04", "rolled-in scale 결함 대응 절차 알려줘", [K]),
    Task("h-k05", "패치 결함 판정 기준 좀 설명해줄래", [K]),
    Task("h-k06", "How should operators handle pitted surface defects?", [K]),
    Task("h-k07", "스크래치랑 크레이징 차이가 뭐야", [K]),
    Task("h-k08", "재검사 들어가는 조건이 어떻게 돼?", [K]),
    Task("h-k09", "크래이징 조치 방볍", [K]),  # 오타
    Task("h-k10", "불량 나왔을 때 SOP상 보고 라인은?", [K]),
    # ── analytics: 집계·추세·비교 (키워드 없는 의도 포함) ──────────────────────
    Task("h-a01", "어느 라인이 제일 문제 많아?", [A]),
    Task("h-a02", "지난주 대비 이번주 불량률 어떻게 변했어", [A]),
    Task("h-a03", "제품 B는 검사 몇 번 했지?", [A]),
    Task("h-a04", "결함 종류별로 몇 개씩 나왔는지 뽑아줘", [A]),
    Task("h-a05", "Which line had the most high-severity defects?", [A]),
    Task("h-a06", "신뢰도 0.7 미만으로 판정된 건 몇 건이야", [A]),
    Task("h-a07", "요즘 스크래치가 늘고 있어? 추이 보여줘", [A]),
    Task("h-a08", "라인 2 불량 비율", [A]),
    # ── 복합: analytics/knowledge + report ───────────────────────────────────
    Task("h-m01", "라인별 불량 현황 정리해서 주간 보고서로 만들어줘", [A, R]),
    Task("h-m02", "크레이징 대응 절차를 문서로 정리해줘", [K, R]),
    Task("h-m03", "불량이 제일 많은 결함 종류 찾고 그 조치 방법도 알려줘", [A, K, R]),
    Task("h-m04", "Summarize defect counts per product into a report", [A, R]),
    Task("h-m05", "high 심각도 건수 뽑고 해당 SOP 처리 기준까지 같이 줘", [A, K, R]),
    Task("h-m06", "피팅 결함 처리 절차를 보고서 형식으로", [K, R]),
    # ── 이미지 ──────────────────────────────────────────────────────────────
    Task("h-v01", "이거 괜찮은 제품이야?", [V], image_path=IMG),
    Task("h-v02", "사진 속 표면 상태 판정해줘", [V], image_path=IMG),
    Task("h-v03", "Is this part defective?", [V], image_path=IMG),
    Task("h-v04", "이 사진 판정하고 결과 보고서로 남겨줘", [V, R], image_path=IMG),
    Task("h-v05", "이 부품 검사해 보고 불량이면 조치 절차도 알려줘", [V, K, R], image_path=IMG),
    Task("h-v06", "이 제품 판정하고 같은 라인 최근 불량 건수도 같이 봐줘", [V, A, R], image_path=IMG),
    Task("h-v07", "봐줘", [V], image_path=IMG),
    # ── 오프토픽(근거 게이트 경로) ─────────────────────────────────────────────
    Task("h-o01", "퇴근하고 뭐 먹을까", [K]),
    Task("h-o02", "파이썬 리스트 정렬하는 법 알려줘", [K]),
    Task("h-o03", "What's the weather in Seoul tomorrow?", [K]),
    Task("h-o04", "라인업 좋은 아이돌 추천해줘", [K]),
    Task("h-o05", "요즘 환율 전망 어때?", [K]),  # (실행 전 수정: '보고서 써줘'는 R 포함 여부가 애매)
    # ── 경계: 원인 질문이지만 통계만 원함 / 절차지만 수치만 원함 ─────────────────
    Task("h-b01", "불량 원인별로 건수만 세줘", [A]),
    Task("h-b02", "왜 라인 3에서만 불량이 많은지 데이터로 보여줘", [A]),
    Task("h-b03", "개재물 결함이 생기는 이유가 뭐야", [K]),
    Task("h-b04", "이번 달 몇 건 검사했는지만 알려줘, 보고서는 필요 없어", [A]),
]
