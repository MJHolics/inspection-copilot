"""검색 평가 태스크셋 — 질문 → 정답 SOP 출처.

일부러 **패러프레이즈**(문서에 없는 단어로 같은 뜻)를 섞었다. 어휘 겹침에 의존하는 TF-IDF가
약한 지점이라, dense(의미) 검색의 이득을 정직하게 드러낸다.
"""
from __future__ import annotations

# (query, gold_source). gold_source = app/docs/sop/<name>.md 의 name.
RETRIEVAL_TASKS: list[tuple[str, str]] = [
    # 직접 매칭(어휘 겹침 큼) — TF-IDF도 잘함
    ("스크래치 결함 처리 절차와 롤러 점검", "scratches"),
    ("개재물 판정 기준과 제강 공정 점검", "inclusion"),
    ("크레이징 균열망 압연 냉각 조치", "crazing"),
    ("표면 피팅 산세 과다 부식 처리", "pitted_surface"),
    ("심각도 등급과 사람 검토 기준", "general_inspection"),
    # 패러프레이즈(문서에 없는 표현) — dense의 강점
    ("표면에 길게 선이 그어진 손상이 보여요", "scratches"),         # 긁힘→선/손상
    ("쇳물에 불순물이 섞여 점처럼 박혔어요", "inclusion"),          # 개재물→불순물/점
    ("거북등 모양으로 잔금이 쫙 퍼졌습니다", "crazing"),            # 균열망→잔금
    ("자잘한 구멍이 송송 뚫린 자국", "pitted_surface"),            # 피트→구멍/자국
    ("자동 판정을 못 믿을 때 누가 다시 봐야 하나요", "general_inspection"),  # 신뢰도/사람검토
]
