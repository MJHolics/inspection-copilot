"""근거 영역이 실제 결함을 가리키는가 — NEU-DET 정답 박스로 잰다.

`app/explain.py`의 가림 민감도 지도는 분류기가 판정에 쓴 영역이지 결함 위치가 아니다. 화면에
"결함 위치"라고 써도 되는지는 재 봐야 안다. 지도의 최댓값 지점이 정답 박스 안에 들어가는 비율
(pointing game)을 두 기준과 비교한다.

  · 무작위 : 아무 점이나 찍었을 때의 기대 적중률 = 정답 박스 합집합의 면적 비율
  · 중앙   : 항상 이미지 한가운데를 찍는 경우

사용: python tools/bench_localization.py --data <NEU-DET>/validation
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.detector import load_default_detector  # noqa: E402
from app.explain import occlusion_map  # noqa: E402
from app.vision_model import _MODEL_CLASSES, OnnxVisionPredictor  # noqa: E402


def load_boxes(xml_path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    root = ET.parse(xml_path).getroot()
    w = int(root.findtext("size/width"))
    h = int(root.findtext("size/height"))
    boxes = []
    for obj in root.iter("object"):
        b = obj.find("bndbox")
        boxes.append(tuple(int(b.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax")))
    return w, h, boxes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results/localization.json")
    args = ap.parse_args()

    root = Path(args.data)
    pred = OnnxVisionPredictor()
    det = load_default_detector()
    rows = []
    for cls in _MODEL_CLASSES:
        for img in sorted((root / "images" / cls).glob("*.jpg")):
            xml = root / "annotations" / (img.stem + ".xml")
            if not xml.exists():
                continue
            w, h, boxes = load_boxes(xml)
            mask = np.zeros((h, w), dtype=bool)
            for x0, y0, x1, y1 in boxes:
                mask[y0:y1 + 1, x0:x1 + 1] = True

            t0 = time.perf_counter()
            exp = occlusion_map(pred, str(img))
            ms = (time.perf_counter() - t0) * 1000

            px = min(w - 1, int(exp.peak_xy[0] * w))
            py = min(h - 1, int(exp.peak_xy[1] * h))
            bx0, by0, bx1, by1 = exp.box
            shown = np.zeros((h, w), dtype=bool)
            shown[int(by0 * h):int(np.ceil(by1 * h)), int(bx0 * w):int(np.ceil(bx1 * w))] = True
            # 검출기: 분류기가 말한 종류의 최고 점수 박스 중심이 정답 박스 안에 드는가
            t0 = time.perf_counter()
            boxes_d = det(str(img)) if det else []
            det_ms = (time.perf_counter() - t0) * 1000
            pred_cls = _MODEL_CLASSES[exp.pred_index]
            same = [b for b in boxes_d if b.cls == pred_cls]
            det_hit = False
            if same:
                bx = same[0].xyxy
                cx = min(w - 1, int((bx[0] + bx[2]) / 2 * w))
                cy = min(h - 1, int((bx[1] + bx[3]) / 2 * h))
                det_hit = bool(mask[cy, cx])
            rows.append({
                "det_hit": det_hit, "det_agree": bool(same), "det_any": bool(boxes_d), "det_ms": det_ms,
                "cls": cls, "file": img.name,
                "correct": _MODEL_CLASSES[exp.pred_index] == cls,
                "hit": bool(mask[py, px]),
                "center_hit": bool(mask[h // 2, w // 2]),
                "random": float(mask.mean()),
                "box_precision": float((shown & mask).sum() / max(shown.sum(), 1)),
                "max_drop": exp.max_drop, "ms": ms,
            })

    def agg(rs: list[dict]) -> dict:
        return {
            "n": len(rs),
            "cls_acc": round(float(np.mean([r["correct"] for r in rs])), 4),
            "pointing": round(float(np.mean([r["hit"] for r in rs])), 4),
            "center": round(float(np.mean([r["center_hit"] for r in rs])), 4),
            "random": round(float(np.mean([r["random"] for r in rs])), 4),
            "box_precision": round(float(np.mean([r["box_precision"] for r in rs])), 4),
            "flat_map": round(float(np.mean([r["max_drop"] < 0.01 for r in rs])), 4),
            "ms_median": round(float(np.median([r["ms"] for r in rs])), 1),
            "det_pointing": round(float(np.mean([r["det_hit"] for r in rs])), 4),
            "det_agree": round(float(np.mean([r["det_agree"] for r in rs])), 4),
            "det_any": round(float(np.mean([r["det_any"] for r in rs])), 4),
            "det_ms_median": round(float(np.median([r["det_ms"] for r in rs])), 1),
        }

    out = {"all": agg(rows), "per_class": {c: agg([r for r in rows if r["cls"] == c])
                                           for c in _MODEL_CLASSES}, "rows": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'class':<18}{'n':>4}{'acc':>7}{'point':>7}{'center':>8}{'random':>8}{'boxP':>7}{'flat':>6}{'ms':>7}"
          f"{'detPt':>7}{'agree':>7}{'any':>6}{'detms':>7}")
    for name, a in [*out["per_class"].items(), ("ALL", out["all"])]:
        print(f"{name:<18}{a['n']:>4}{a['cls_acc']:>7.3f}{a['pointing']:>7.3f}{a['center']:>8.3f}"
              f"{a['random']:>8.3f}{a['box_precision']:>7.3f}{a['flat_map']:>6.2f}{a['ms_median']:>7.1f}"
              f"{a['det_pointing']:>7.3f}{a['det_agree']:>7.3f}{a['det_any']:>6.2f}{a['det_ms_median']:>7.1f}")


if __name__ == "__main__":
    main()
