"""자가개선 루프 — 검토 큐 → 재학습 트리거 → 승격 게이트 (순수 로직).

검사 코파일럿이 needs_human(저신뢰/가드 정지)으로 멈춘 건을 검토 큐에 쌓고, 사람이 정답을
교정하면 라벨이 축적된다. 라벨이 임계에 닿거나 드리프트가 뜨면 재학습을 트리거하고, 후보
모델은 **고정 평가셋 승격 게이트**를 통과해야만 운영에 올라간다.

핵심은 **승격 게이트의 안전 우선** — 정확도가 더 높아도 *안전(비용가중 위험)*이 회귀하면
거부한다. VLM Defect Inspector의 실측 게이트(v5/v6 거부·v7 승격)를 순수 로직으로 포팅한 것.
실 재학습/모델 평가는 VLM Defect 레포가 담당하고, 여기선 루프의 *제어 로직*을 결정적으로 시연한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewItem:
    request: str
    route: list[str]
    confidence: float
    corrected_label: str | None = None


@dataclass
class ReviewQueue:
    """needs_human 건을 모아 사람 교정을 받는 큐. 교정 라벨이 재학습 신호가 된다."""

    items: list[ReviewItem] = field(default_factory=list)

    def ingest(self, result) -> bool:
        """SupervisorResult가 needs_human이면 큐에 넣는다. 넣었으면 True."""
        if not getattr(result, "needs_human", False):
            return False
        conf = min((r.confidence for r in result.results), default=0.0)
        self.items.append(ReviewItem(request="", route=list(result.plan.steps), confidence=conf))
        return True

    def correct(self, idx: int, label: str) -> None:
        self.items[idx].corrected_label = label

    @property
    def corrected_count(self) -> int:
        return sum(1 for it in self.items if it.corrected_label)


def should_retrain(corrected_count: int, drift_alert: bool = False, threshold: int = 20) -> bool:
    """재학습 트리거 정책: 교정 라벨 N건 누적 OR 드리프트 alert."""
    return corrected_count >= threshold or drift_alert


@dataclass
class ModelStats:
    name: str
    type_acc: float    # 유형 정확도(높을수록 좋음)
    risk_score: float  # 비용가중 위험(낮을수록 안전; miss×10 / false_alarm×1)


@dataclass
class GateDecision:
    candidate: str
    promote: bool
    reason: str


def evaluate_promotion(current: ModelStats, candidate: ModelStats) -> GateDecision:
    """승격 게이트: **위험 ≤ 현행 AND 정확도 비퇴보**일 때만 승격(둘 다 충족).

    정확도가 더 높아도 안전(위험)이 회귀하면 거부한다 — 게이트는 정확도가 아니라 위험으로
    판정한다. 동률(≤)은 통과(VLM Defect v7 사례: 위험 동률·정확도 +3%p → 승격).
    """
    eps = 1e-9
    safe = candidate.risk_score <= current.risk_score + eps
    non_regress = candidate.type_acc >= current.type_acc - eps
    if safe and non_regress:
        return GateDecision(
            candidate.name, True,
            f"위험 {candidate.risk_score:.4f}≤{current.risk_score:.4f} AND "
            f"정확도 {candidate.type_acc:.1%}(비퇴보) → 승격",
        )
    if not safe:
        return GateDecision(
            candidate.name, False,
            f"정확도 {candidate.type_acc:.1%}로 높아도 위험 {candidate.risk_score:.4f}>"
            f"{current.risk_score:.4f}(안전 회귀) → 거부",
        )
    return GateDecision(
        candidate.name, False,
        f"위험은 통과지만 정확도 퇴보({candidate.type_acc:.1%}<{current.type_acc:.1%}) → 거부",
    )
