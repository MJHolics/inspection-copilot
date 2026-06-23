"""실 ONNX 비전 모델 테스트 — 의존성/모델 있으면 실행, 없으면 skip.

trust 층(순수)과 달리 이 테스트는 실제 모델 추론 경로를 검증한다. CI에 onnxruntime이 없으면
자동 skip(코어 단위테스트는 영향 없음).
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("numpy")
pytest.importorskip("PIL")

from app import config  # noqa: E402
from app.agents import AgentRequest  # noqa: E402
from app.agents.vision import VisionAgent  # noqa: E402
from app.vision_model import MODEL_PATH, load_default_predictor  # noqa: E402

_SAMPLE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples", "sample_01.jpg")


@pytest.mark.skipif(not os.path.exists(MODEL_PATH), reason="ONNX 모델 파일 없음")
def test_predictor_returns_valid_distribution():
    pred = load_default_predictor()
    assert pred is not None
    probs = pred(_SAMPLE)
    assert len(probs) == len(config.DEFECT_CLASSES)
    assert abs(sum(probs) - 1.0) < 1e-4  # softmax 합 ≈ 1
    assert all(0.0 <= p <= 1.0 for p in probs)


@pytest.mark.skipif(not os.path.exists(_SAMPLE), reason="샘플 이미지 없음")
def test_vision_agent_with_real_model():
    agent = VisionAgent(predictor=load_default_predictor())
    res = agent.run(AgentRequest(text="검사", image_path=_SAMPLE))
    assert res.ok
    assert res.data["pred_class"] in config.DEFECT_CLASSES
    assert res.data["model_loaded"] is True
