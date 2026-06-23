"""Vision 에이전트 테스트 — predictor 주입·trust 게이트·모델 미로딩 안전멈춤. 오프라인."""
from __future__ import annotations

from app import config
from app.agents import AgentRequest
from app.agents.vision import VisionAgent


def _probs(top: str, conf: float = 0.9):
    p = [(1 - conf) / (len(config.DEFECT_CLASSES) - 1)] * len(config.DEFECT_CLASSES)
    p[config.DEFECT_CLASSES.index(top)] = conf
    return p


def test_no_image():
    res = VisionAgent(predictor=lambda p: _probs("scratches")).run(AgentRequest(text="검사"))
    assert not res.ok and res.error == "no_image"


def test_no_model_stops_for_human():
    res = VisionAgent(predictor=None).run(AgentRequest(text="검사", image_path="x.jpg"))
    assert res.ok and res.needs_human
    assert res.data["model_loaded"] is False


def test_confident_prediction_passes():
    agent = VisionAgent(predictor=lambda p: _probs("scratches", 0.9))
    res = agent.run(AgentRequest(text="검사", image_path="x.jpg"))
    assert res.ok and not res.needs_human
    assert res.data["pred_class"] == "scratches"
    assert res.data["conformal_set"] == ["scratches"]
    assert not res.data["ood"]


def test_low_confidence_routes_to_human():
    # 균등에 가까운 분포 → 최대 신뢰도 낮음 → OOD 게이트 → needs_human.
    agent = VisionAgent(predictor=lambda p: [1 / 6] * 6)
    res = agent.run(AgentRequest(text="검사", image_path="x.jpg"))
    assert res.needs_human and res.data["ood"]


def test_inference_failure_handled():
    def boom(path):
        raise RuntimeError("model crash")

    res = VisionAgent(predictor=boom).run(AgentRequest(text="검사", image_path="x.jpg"))
    assert not res.ok and res.needs_human and res.error == "inference_failed"
