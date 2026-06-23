"""Vision Inspection 에이전트 — 이미지 결함 분류 + trust 게이트(conformal·OOD·신뢰도).

predictor(image_path) → 클래스 확률(softmax)을 받아 `trust.assess`로 예측·conformal 예측집합·
신뢰도/OOD를 판정한다. 애매하거나 분포 밖이면 needs_human=True로 멈춘다("모를 때 멈춤").

predictor는 주입식 — 이 레포는 분류 모델 가중치를 담지 않으므로 기본은 None이고, 모델이 없으면
검사 불가로 안전하게 사람검토를 요청한다. 실모델은 `vlm-defect-inspector`의 ResNet18/MobileNetV3
(ONNX) 추론을 predictor로 감싸 주입한다(torch/onnxruntime는 그 환경에서). trust 층 자체는 순수·
오프라인이라, predictor만 주입하면 전체 경로가 결정적으로 테스트된다.
"""
from __future__ import annotations

from .. import config
from ..trust import DEFAULT_CONF_GATE, DEFAULT_QHAT, assess
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

    def __init__(self, predictor=None, classes=None, qhat: float = DEFAULT_QHAT,
                 conf_gate: float = DEFAULT_CONF_GATE) -> None:
        # predictor(image_path) -> list[float] (self.classes에 정렬된 softmax 확률)
        self.predictor = predictor
        self.classes = list(classes) if classes else list(config.DEFECT_CLASSES)
        self.qhat = qhat
        self.conf_gate = conf_gate

    def run(self, req: AgentRequest) -> AgentResult:
        if not req.image_path:
            return AgentResult(
                agent=self.name, ok=False,
                summary="이미지가 없어 비전 검사를 수행할 수 없습니다.", error="no_image",
            )
        if self.predictor is None:
            # 모델 미로딩 — 추측 대신 안전 멈춤(trust 원칙).
            return AgentResult(
                agent=self.name, ok=True,
                summary="비전 분류 모델이 로딩되지 않아 자동 판정을 보류합니다(사람 검토 필요).",
                confidence=0.0, needs_human=True,
                data={"model_loaded": False},
            )
        try:
            probs = self.predictor(req.image_path)
        except Exception as e:
            return AgentResult(
                agent=self.name, ok=False, summary=f"추론 실패: {e}",
                confidence=0.0, needs_human=True, error="inference_failed",
            )

        d = assess(probs, self.classes, qhat=self.qhat, conf_gate=self.conf_gate)
        flag = "" if not d.needs_human else " — 사람 검토 필요"
        summary = (
            f"예측: {d.pred_class}(신뢰도 {d.confidence:.2f}) · "
            f"conformal 집합 {{{', '.join(d.conformal_set) or '∅'}}}{flag}. {d.reason}"
        )
        evidence = [Evidence(
            source=f"image:{req.image_path}",
            detail=f"trust: ood={d.ood}, ambiguous={d.ambiguous}, set={d.conformal_set}",
            score=round(d.confidence, 4),
        )]
        return AgentResult(
            agent=self.name, ok=True, summary=summary, evidence=evidence,
            confidence=round(d.confidence, 3), needs_human=d.needs_human,
            data={
                "model_loaded": True,
                "pred_class": d.pred_class,
                "conformal_set": d.conformal_set,
                "ood": d.ood,
                "ambiguous": d.ambiguous,
            },
        )
