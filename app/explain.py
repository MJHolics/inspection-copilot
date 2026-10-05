"""판정 근거 영역 — 가림 민감도(occlusion sensitivity)로 "어디를 보고 그렇게 판정했나"를 그린다.

분류 모델(ONNX)은 클래스 확률만 내고 위치를 내지 않는다. 그래서 이미지의 한 조각을 평균 밝기로
가리고 다시 추론해, 예측 클래스 확률이 얼마나 떨어지는지를 조각마다 잰다. 많이 떨어지는 곳이
판정에 쓰인 영역이다. 그래디언트가 필요 없어 torch 없이 onnxruntime 배치 추론 한 번으로 끝난다.

이 지도는 **분류기의 근거 영역**이지 검출기의 결함 박스가 아니다. 실제 결함 위치와 얼마나 겹치는지는
`tools/bench_localization.py`가 NEU-DET 정답 박스로 잰다.
"""
from __future__ import annotations

from dataclasses import dataclass

PATCH = 48      # 가리는 조각 한 변(입력 224 기준)
STRIDE = 16


@dataclass
class Explanation:
    heat: object                 # (H, W) float32, 0~1 — 클수록 판정에 많이 쓰인 영역
    pred_index: int
    base_prob: float
    max_drop: float              # 한 조각을 가렸을 때 확률이 가장 많이 떨어진 폭
    peak_xy: tuple[float, float]  # 지도 최댓값 위치(0~1 정규화, x·y)
    box: tuple[float, float, float, float]  # 상위 영역의 외접 박스(0~1 정규화, x0 y0 x1 y1)


def occlusion_map(predictor, image_path: str, patch: int = PATCH, stride: int = STRIDE,
                  box_level: float = 0.6) -> Explanation:
    """predictor(OnnxVisionPredictor)로 가림 민감도 지도를 만든다."""
    import numpy as np

    x = predictor.preprocess(image_path)             # (1,3,S,S)
    size = x.shape[-1]
    base = predictor.predict_batch(x)[0]
    pred = int(base.argmax())
    fill = x.mean(axis=(2, 3), keepdims=True)        # 채널별 평균 밝기로 가린다

    starts = list(range(0, size - patch + 1, stride))
    batch = np.repeat(x, len(starts) ** 2, axis=0)
    k = 0
    for y0 in starts:
        for x0 in starts:
            batch[k, :, y0:y0 + patch, x0:x0 + patch] = fill[0]
            k += 1
    drops = base[pred] - predictor.predict_batch(batch)[:, pred]

    acc = np.zeros((size, size), dtype="float32")
    cnt = np.zeros((size, size), dtype="float32")
    k = 0
    for y0 in starts:
        for x0 in starts:
            acc[y0:y0 + patch, x0:x0 + patch] += max(float(drops[k]), 0.0)
            cnt[y0:y0 + patch, x0:x0 + patch] += 1.0
            k += 1
    heat = acc / np.maximum(cnt, 1.0)
    top = float(heat.max())
    if top > 0:
        heat = heat / top

    py, px = np.unravel_index(int(heat.argmax()), heat.shape)
    ys, xs = np.where(heat >= box_level) if top > 0 else (np.array([0, size - 1]), np.array([0, size - 1]))
    box = (xs.min() / size, ys.min() / size, (xs.max() + 1) / size, (ys.max() + 1) / size)
    return Explanation(heat=heat, pred_index=pred, base_prob=float(base[pred]),
                       max_drop=float(max(drops.max(), 0.0)),
                       peak_xy=((px + 0.5) / size, (py + 0.5) / size), box=box)


def overlay(image_path: str, exp: Explanation, out_path: str, width: int = 480,
            alpha: float = 0.45) -> str:
    """원본 위에 근거 영역을 붉게 얹고 상위 영역에 테두리를 그려 저장한다."""
    import numpy as np
    from PIL import Image, ImageDraw

    img = Image.open(image_path).convert("RGB").resize((width, width), Image.BICUBIC)
    heat = Image.fromarray((exp.heat * 255).astype("uint8")).resize((width, width), Image.BICUBIC)
    h = np.asarray(heat, dtype="float32")[..., None] / 255.0
    base = np.asarray(img, dtype="float32")
    red = np.array([230.0, 40.0, 40.0], dtype="float32")
    mixed = base * (1 - alpha * h) + red * (alpha * h)
    out = Image.fromarray(mixed.clip(0, 255).astype("uint8"))
    x0, y0, x1, y1 = (v * width for v in exp.box)
    ImageDraw.Draw(out).rectangle([x0, y0, x1 - 1, y1 - 1], outline=(255, 214, 0), width=3)
    out.save(out_path)
    return out_path
