"""실 비전 분류 모델 — Vision 에이전트에 주입하는 ONNX predictor.

`vlm-defect-inspector`의 엣지 CNN(MobileNetV3-Small, 1.52M·6MB, ONNX)을 그대로 가져와 감쌌다.
torch 없이 onnxruntime + numpy + pillow만으로 CPU 수 ms 추론한다. 전처리(grayscale→224→
ImageNet 정규화)는 원본 학습/배포와 동일하게 포팅했다 — 어긋나면 신뢰도가 무의미해지므로 충실히.

predictor(image_path) → config.DEFECT_CLASSES 순서의 softmax 확률 리스트. 이 출력이 곧 Vision
에이전트의 trust 게이트(conformal·OOD) 입력이 된다. 의존성/모델이 없으면 load_default_predictor()는
None을 돌려주고, Vision 에이전트는 안전하게 사람검토로 멈춘다.
"""
from __future__ import annotations

import os

from . import config

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "vision_mobilenet_v3s.onnx")

# 모델 학습 클래스 순서 — config.DEFECT_CLASSES와 동일해야 한다(정렬 검증은 생성자에서).
_MODEL_CLASSES = ["crazing", "inclusion", "patches", "pitted_surface", "rolled-in_scale", "scratches"]
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


class OnnxVisionPredictor:
    """ONNX 엣지 CNN 추론기. __call__(image_path) → softmax 확률(DEFECT_CLASSES 정렬)."""

    def __init__(self, model_path: str = MODEL_PATH, size: int = 224) -> None:
        import onnxruntime as ort  # 지연 import(선택 의존성)

        if _MODEL_CLASSES != list(config.DEFECT_CLASSES):
            raise ValueError("모델 클래스 순서가 config.DEFECT_CLASSES와 다릅니다.")
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(model_path, so, providers=["CPUExecutionProvider"])
        self._input = self._sess.get_inputs()[0].name
        self.size = size

    def _preprocess(self, image_path: str):
        import numpy as np
        from PIL import Image

        img = Image.open(image_path).convert("L").resize((self.size, self.size), Image.BILINEAR)
        x = np.asarray(img, dtype="float32") / 255.0
        x = np.stack([x, x, x], axis=0)  # grayscale → 3채널 복제
        mean = np.array(_IMAGENET_MEAN, dtype="float32")[:, None, None]
        std = np.array(_IMAGENET_STD, dtype="float32")[:, None, None]
        x = (x - mean) / std
        return x[None].astype("float32")  # (1,3,H,W)

    def __call__(self, image_path: str) -> list[float]:
        import numpy as np

        logits = self._sess.run(None, {self._input: self._preprocess(image_path)})[0][0]
        z = logits - logits.max()
        e = np.exp(z)
        probs = e / e.sum()
        return [float(p) for p in probs]


def load_default_predictor():
    """기본 ONNX predictor를 만든다. 의존성/모델이 없으면 None(→ Vision 안전 멈춤)."""
    try:
        if not os.path.exists(MODEL_PATH):
            return None
        return OnnxVisionPredictor()
    except Exception:
        return None
