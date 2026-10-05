"""결함 검출기 — "어디에 있나"를 박스로 낸다(YOLOv8n, ONNX).

분류 모델(`vision_model.py`)은 종류와 확신도만 낸다. 위치는 NEU-DET 정답 박스로 학습한 검출기가
따로 낸다(`vlm-defect-inspector/scripts/train_detector.py`). ultralytics 없이 onnxruntime + numpy로
돌리려고 후처리(NMS)를 직접 썼다. 모델 파일이 없으면 load_default_detector()는 None을 돌려준다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import config

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "defect_yolov8n.onnx")


@dataclass
class Box:
    cls: str
    score: float
    xyxy: tuple[float, float, float, float]  # 0~1 정규화(x0 y0 x1 y1)


def _nms(boxes, scores, iou_thr: float):
    import numpy as np

    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        xx0 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy0 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx1 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy1 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx1 - xx0, 0, None) * np.clip(yy1 - yy0, 0, None)
        area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])  # noqa: E731
        iou = inter / (area(boxes[i]) + area(boxes[rest]) - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return keep


class OnnxDefectDetector:
    """__call__(image_path) → 점수 내림차순 Box 목록."""

    def __init__(self, model_path: str = MODEL_PATH, conf: float = 0.25, iou: float = 0.5) -> None:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(model_path, so, providers=["CPUExecutionProvider"])
        inp = self._sess.get_inputs()[0]
        self._input = inp.name
        self.size = int(inp.shape[-1])
        self.conf = conf
        self.iou = iou
        self.classes = list(config.DEFECT_CLASSES)

    def __call__(self, image_path: str) -> list[Box]:
        import numpy as np
        from PIL import Image

        img = Image.open(image_path).convert("RGB").resize((self.size, self.size), Image.BILINEAR)
        x = (np.asarray(img, dtype="float32") / 255.0).transpose(2, 0, 1)[None]
        out = self._sess.run(None, {self._input: x})[0][0].T      # (N, 4 + 클래스 수)
        scores = out[:, 4:].max(axis=1)
        m = scores >= self.conf
        out, scores = out[m], scores[m]
        if not len(out):
            return []
        cls = out[:, 4:].argmax(axis=1)
        cx, cy, w, h = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
        xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1) / self.size
        xyxy = xyxy.clip(0, 1)
        keep = []
        for c in np.unique(cls):                                   # 클래스별 NMS
            idx = np.where(cls == c)[0]
            keep += [int(idx[k]) for k in _nms(xyxy[idx], scores[idx], self.iou)]
        keep.sort(key=lambda i: -scores[i])
        return [Box(self.classes[int(cls[i])], float(scores[i]), tuple(float(v) for v in xyxy[i]))
                for i in keep]


def load_default_detector():
    """기본 검출기를 만든다. 의존성/모델이 없으면 None(위치 표시 없이 종류만 판정)."""
    try:
        if not os.path.exists(MODEL_PATH):
            return None
        return OnnxDefectDetector()
    except Exception:
        return None
