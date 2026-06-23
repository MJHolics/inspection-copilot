"""Eval 골든 태스크셋 — 큐레이션된 검사 질문과 기대 동작.

각 태스크는 기대 라우트(어떤 에이전트를 어떤 순서로), 기대 그라운딩 출처(knowledge),
기대 사람검토 여부(가드레일), 태그를 명시한다. 이 골든셋에 대해 시스템을 돌려
라우팅 정확도·그라운딩 충실도·게이트 정확도·e2e 성공률을 수치화한다(run_eval).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    question: str
    expected_route: list[str]
    expected_top_source: str | None = None  # knowledge 그라운딩 기대 출처(SOP id)
    expect_needs_human: bool = False        # 가드레일 기대(근거 부족/저신뢰면 True)
    image_path: str | None = None
    tags: list[str] = field(default_factory=list)


GOLDEN: list[Task] = [
    # --- Knowledge 그라운딩 ---
    Task("kn-scr", "스크래치 결함은 어떤 절차로 처리해?", ["knowledge"],
         expected_top_source="scratches", tags=["routing", "grounding"]),
    Task("kn-crz", "크레이징 결함 원인과 조치 알려줘", ["knowledge"],
         expected_top_source="crazing", tags=["routing", "grounding"]),
    Task("kn-inc", "개재물 판정 기준이 뭐야?", ["knowledge"],
         expected_top_source="inclusion", tags=["routing", "grounding"]),
    Task("kn-pit", "표면 피팅 처리 방법과 절차", ["knowledge"],
         expected_top_source="pitted_surface", tags=["routing", "grounding"]),
    # --- 가드레일: 근거 부족 → 멈춤 ---
    Task("gate-off", "오늘 점심 메뉴랑 날씨 알려줘", ["knowledge"],
         expect_needs_human=True, tags=["routing", "guardrail"]),
    # --- Analytics(NL2SQL, 실 DB 실행) ---
    Task("an-line", "라인별 불량 건수 알려줘", ["analytics"], tags=["routing", "analytics"]),
    Task("an-sev", "high 심각도 불량 통계 내줘", ["analytics"], tags=["routing", "analytics"]),
    Task("an-prod", "제품별 평균 신뢰도 추세", ["analytics"], tags=["routing", "analytics"]),
    # --- 멀티에이전트 + 종합 리포트 ---
    Task("multi-kn-rep", "스크래치 처리 절차 정리해서 보고서로 줘", ["knowledge", "report"],
         expected_top_source="scratches", tags=["routing", "grounding", "multi"]),
    Task("multi-an-rep", "라인별 불량 건수 통계로 보고서 만들어줘", ["analytics", "report"],
         tags=["routing", "analytics", "multi"]),
    # --- 이미지 → Vision(실 trust 게이트, eval은 결정적 predictor 주입) ---
    Task("img-vis", "이 사진 불량인지 검사해줘", ["vision"],
         image_path="samples/x.jpg", tags=["routing", "vision"]),
    Task("img-multi", "이 사진 검사하고 라인별 불량 통계로 보고서 줘",
         ["vision", "analytics", "report"], image_path="samples/x.jpg",
         tags=["routing", "vision", "analytics", "multi"]),
    Task("img-rep", "이 사진 검사하고 결과를 보고서로 정리해줘", ["vision", "report"],
         image_path="samples/x.jpg", tags=["routing", "vision", "multi"]),
    # --- 추가 그라운딩·분석 케이스(커버리지 확대) ---
    Task("kn-pit2", "피팅 결함의 원인과 조치 기준을 설명해줘", ["knowledge"],
         expected_top_source="pitted_surface", tags=["routing", "grounding"]),
    Task("an-month", "이번 달 검사 건수 알려줘", ["analytics"], tags=["routing", "analytics"]),
]
