"""Vision Inspection 에이전트 (P1 스텁).

이미지 → 결함 감지(YOLO) + 해석(VLM) + **trust 층**(confidence·OOD·conformal 게이트).
애매하면 needs_human=True로 멈춘다 — 이 trust 게이트가 이 에이전트의 핵심 차별점.

P1에서는 인터페이스만 고정한다. 실제 추론은 P2에서 `vlm-defect-inspector`(VLM·confidence·
OOD·conformal)와 `vision-inspection-agent`(YOLO·PDF) 자산을 이식해 채운다.
"""
from __future__ import annotations

from .base import AgentRequest, AgentResult, BaseAgent, Evidence


class VisionAgent(BaseAgent):
    name = "vision"
    description = (
        "이미지 속 표면 결함을 감지·분류하고 심각도와 신뢰도를 매긴다. "
        "신뢰도가 낮거나 분포 밖(OOD)이면 사람검토로 넘긴다. 이미지가 있으면 호출한다."
    )
    keywords = (
        "이미지", "사진", "결함", "불량", "스크래치", "긁힘", "찍힘", "균열",
        "defect", "scratch", "crack", "inclusion", "patch", "검사해", "분류해",
    )

    def run(self, req: AgentRequest) -> AgentResult:
        if not req.image_path:
            return AgentResult(
                agent=self.name,
                ok=False,
                summary="이미지가 없어 비전 검사를 수행할 수 없습니다.",
                error="no_image",
            )
        # TODO(P2): YOLO 감지 → 크롭 → VLM 결함해석 → conformal/OOD trust 게이트.
        #           self.confidence < tau 또는 OOD면 needs_human=True.
        return AgentResult(
            agent=self.name,
            ok=True,
            summary=f"[스텁] '{req.image_path}'에서 결함 감지·분류 예정(P2). trust 게이트 적용.",
            evidence=[Evidence(source=f"image:{req.image_path}", detail="감지 박스(예정)", score=None)],
            confidence=0.0,  # 스텁이라 신뢰도 미정 — P2에서 실제 모델 점수로 대체
            needs_human=False,
            data={"detections": [], "stub": True},
        )
