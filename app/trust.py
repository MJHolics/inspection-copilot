"""Trust 층 — 비전 판정의 신뢰성 게이트(conformal 예측집합 + 신뢰도/OOD).

`vlm-defect-inspector`의 conformal(LAC/APS)·OOD 방법론을 순수 파이썬으로 충실 포팅한 것.
모델의 클래스 확률(softmax) 한 벡터를 받아 ①예측·신뢰도 ②conformal 예측집합(애매성) ③신뢰도/
OOD 게이트를 계산해, 불확실하면 needs_human=True로 멈춘다("모를 때 멈춤").

핵심:
  • LAC  : 집합 = {y : p_y ≥ 1 − q̂}. 작고 효율적. 집합 크기 ≠ 1이면 애매(또는 분포 밖).
  • OOD  : 최대 신뢰도 < 게이트(기본 0.8)면 분포 밖 의심 → 사람검토.
캘리브레이션(lac_calibrate 등)도 함께 제공해, 검증 데이터가 있으면 q̂를 직접 추정할 수 있다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# vlm-defect-inspector 레짐 기본값(alpha=0.1). 실 검증셋이 있으면 lac_calibrate로 대체한다.
DEFAULT_QHAT = 0.85          # LAC 임계 1−q̂ = 0.15 (희소 집합)
DEFAULT_CONF_GATE = 0.8      # OOD/신뢰도 게이트(edge_ood_verify.json gate=0.8)


def conformal_quantile(scores: list[float], alpha: float) -> float:
    """분할 conformal 분위수 q̂ = ⌈(n+1)(1−α)⌉/n 경험분위수(higher 보간). 순수 함수."""
    n = len(scores)
    if n == 0:
        return 1.0
    level = min(1.0, math.ceil((n + 1) * (1.0 - alpha)) / n)
    s = sorted(scores)
    idx = min(n - 1, max(0, math.ceil(level * n) - 1))
    return s[idx]


def lac_calibrate(cal_probs: list[list[float]], cal_labels: list[int], alpha: float) -> float:
    """LAC 캘리브: 비순응점수 s = 1 − p_true 의 conformal 분위수 → q̂."""
    scores = [1.0 - probs[y] for probs, y in zip(cal_probs, cal_labels)]
    return conformal_quantile(scores, alpha)


def lac_set(probs: list[float], qhat: float) -> list[int]:
    """LAC 예측집합 인덱스: p_y ≥ 1 − q̂ 인 클래스."""
    thr = 1.0 - qhat
    return [i for i, p in enumerate(probs) if p >= thr]


def aps_set(probs: list[float], qhat: float) -> list[int]:
    """APS 예측집합: 내림차순 누적합이 q̂를 넘기 직전까지 + 넘기는 클래스 1개 포함."""
    order = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    chosen: list[int] = []
    csum = 0.0
    for i in order:
        before = csum
        csum += probs[i]
        if before < qhat:
            chosen.append(i)
        else:
            break
    return chosen


@dataclass
class TrustDecision:
    pred_index: int
    pred_class: str
    confidence: float
    conformal_set: list[str] = field(default_factory=list)
    ambiguous: bool = False        # 집합 크기 ≠ 1
    ood: bool = False              # 신뢰도 < 게이트
    needs_human: bool = False
    reason: str = ""


def assess(
    probs: list[float],
    classes: list[str],
    *,
    qhat: float = DEFAULT_QHAT,
    conf_gate: float = DEFAULT_CONF_GATE,
) -> TrustDecision:
    """확률 벡터 → trust 판정. 신뢰도 낮거나(OOD) 집합이 애매하면 needs_human."""
    if not probs:
        return TrustDecision(-1, "unknown", 0.0, needs_human=True, reason="빈 예측")
    pred = max(range(len(probs)), key=lambda i: probs[i])
    conf = probs[pred]
    lac = lac_set(probs, qhat)
    set_names = [classes[i] for i in lac]
    ood = conf < conf_gate
    ambiguous = len(lac) != 1

    needs_human = ood or ambiguous
    if ood and ambiguous:
        reason = f"신뢰도 낮음({conf:.2f}<{conf_gate}) + 예측집합 애매(크기 {len(lac)})"
    elif ood:
        reason = f"신뢰도 낮음({conf:.2f}<{conf_gate}) — 분포 밖(OOD) 의심"
    elif ambiguous:
        reason = f"예측집합 애매(크기 {len(lac)}) — 단일 클래스로 좁혀지지 않음"
    else:
        reason = f"신뢰도 충분({conf:.2f}) + 단일 예측집합"

    return TrustDecision(
        pred_index=pred, pred_class=classes[pred], confidence=conf,
        conformal_set=set_names, ambiguous=ambiguous, ood=ood,
        needs_human=needs_human, reason=reason,
    )
