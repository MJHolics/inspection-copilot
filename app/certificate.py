"""검사 성적서 — 사진 한 장을 "위치가 표시된 사진 + 판정 + 조치 + PDF"로 만든다.

supervisor 경로(질문 라우팅)와 별개인 제품 화면용 조립 층이다. 새 판단을 하지 않고 이미 있는
부품을 그대로 쓴다.

  · 종류·확신도  : `vision_model.py` 분류기 + `trust.assess`(확신도 게이트·후보 집합)
  · 위치        : `detector.py` 검출기 박스
  · 판정 기준·조치: `docs/sop/<결함>.md` 원문에서 그대로 발췌(생성하지 않는다)

분류기와 검출기는 따로 학습한 두 모델이다. 둘이 같은 종류를 말하지 않으면 자동 판정을 멈춘다.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config
from .detector import MODEL_PATH as DETECTOR_PATH
from .detector import Box
from .retrieval import DOCS_DIR
from .trust import DEFAULT_CONF_GATE, assess
from .vision_model import MODEL_PATH as CLASSIFIER_PATH

KO = {
    "crazing": "크레이징(미세 균열망)",
    "inclusion": "개재물",
    "patches": "패치(얼룩)",
    "pitted_surface": "피팅(표면 구멍)",
    "rolled-in_scale": "압입 스케일",
    "scratches": "스크래치",
}
MAX_BOXES = 5
_KST = timezone(timedelta(hours=9))


@dataclass
class Certificate:
    cert_id: str
    issued: str
    image_name: str
    defect: str
    defect_ko: str
    confidence: float
    needs_human: bool
    verdict: str
    reasons: list[str] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)
    sop_id: str = ""
    criteria: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    model_version: str = ""
    overlay_path: str | None = None


def _file_tag(path: str) -> str:
    if not os.path.exists(path):
        return "없음"
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:8]


def _sop_section(text: str, heading: str) -> list[str]:
    """SOP 마크다운에서 `## heading…` 아래 목록 항목을 원문 그대로 뽑는다."""
    m = re.search(rf"^## {heading}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        return []
    return [re.sub(r"^(\d+\.|-)\s*", "", ln).replace("**", "").strip()
            for ln in m.group(1).splitlines() if re.match(r"^(\d+\.|-)\s", ln)]


def load_sop(defect: str) -> tuple[str, list[str], list[str]]:
    """(문서 id, 판정 기준, 조치). 결함별 문서가 없으면 일반 기준의 공통 처리 흐름을 쓴다."""
    path = os.path.join(DOCS_DIR, f"{defect}.md")
    if os.path.exists(path):
        text = open(path, encoding="utf-8").read()
        sop_id = text.splitlines()[0].lstrip("# ").split(" — ")[0]
        return sop_id, _sop_section(text, "판정 기준"), _sop_section(text, "조치")
    path = os.path.join(DOCS_DIR, "general_inspection.md")
    if os.path.exists(path):
        text = open(path, encoding="utf-8").read()
        return "SOP-GEN", [], _sop_section(text, "공통 처리 흐름")
    return "", [], []


def issue(image_path: str, predictor, detector=None) -> Certificate:
    """사진 한 장 → 성적서. predictor는 필수, detector가 없으면 위치 없이 종류만 판정한다."""
    probs = predictor(image_path)
    classes = list(config.DEFECT_CLASSES)
    d = assess(probs, classes)
    boxes_all = detector(image_path) if detector is not None else []
    same = [b for b in boxes_all if b.cls == d.pred_class]
    ko = KO.get(d.pred_class, d.pred_class)

    reasons = [f"분류 모델이 {ko}로 봤습니다. 확신도 {d.confidence:.0%}."]
    needs_human = d.needs_human
    if d.ood:
        reasons.append(f"확신도가 자동 판정 기준({DEFAULT_CONF_GATE:.0%})보다 낮습니다. "
                       "학습 때 보지 못한 유형일 수 있습니다.")
    if d.ambiguous:
        if d.conformal_set:
            names = ", ".join(KO.get(c, c) for c in d.conformal_set)
            reasons.append(f"후보가 한 종류로 좁혀지지 않습니다: {names}.")
        else:
            reasons.append("기준을 넘는 후보 종류가 없습니다.")
    if detector is not None:
        if same:
            area = sum((b.xyxy[2] - b.xyxy[0]) * (b.xyxy[3] - b.xyxy[1]) for b in same[:MAX_BOXES])
            reasons.append(f"검출 모델이 같은 종류의 결함을 {len(same[:MAX_BOXES])}곳에서 찾았습니다"
                           f"(박스 면적 합 {min(area, 1.0):.0%}).")
        elif boxes_all:
            other = KO.get(boxes_all[0].cls, boxes_all[0].cls)
            reasons.append(f"검출 모델은 {other}로 봤습니다. 두 모델의 판단이 다릅니다.")
            needs_human = True
        else:
            reasons.append("검출 모델이 결함 위치를 찾지 못했습니다.")
            needs_human = True

    sop_id, criteria, actions = load_sop(d.pred_class)
    if needs_human:
        verdict = "사람 확인 필요"
        actions = ["자동 판정을 보류하고 검사 담당자가 직접 확인한다.", *actions]
    else:
        verdict = f"결함 확인: {ko}"

    shown = same[:MAX_BOXES] if same else boxes_all[:MAX_BOXES]
    return Certificate(
        cert_id=f"IC-{datetime.now(_KST):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        issued=f"{datetime.now(_KST):%Y-%m-%d %H:%M:%S} KST",
        image_name=os.path.basename(image_path),
        defect=d.pred_class, defect_ko=ko, confidence=float(d.confidence),
        needs_human=needs_human, verdict=verdict, reasons=reasons, boxes=shown,
        sop_id=sop_id, criteria=criteria, actions=actions,
        model_version=f"분류 {_file_tag(CLASSIFIER_PATH)} · 검출 {_file_tag(DETECTOR_PATH)}",
    )


def draw_overlay(image_path: str, cert: Certificate, out_path: str, width: int = 520) -> str:
    """원본 위에 결함 박스와 번호를 그린다. 사람 확인 건은 주황, 자동 판정 건은 빨강."""
    from PIL import Image, ImageDraw

    img = Image.open(image_path).convert("RGB").resize((width, width), Image.BICUBIC)
    draw = ImageDraw.Draw(img, "RGBA")
    color = (255, 150, 0) if cert.needs_human else (235, 45, 45)
    for i, b in enumerate(cert.boxes, 1):
        x0, y0, x1, y1 = (v * width for v in b.xyxy)
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(*color, 255), width=3,
                       fill=(*color, 36))
        draw.rectangle([x0, y0, x0 + 20, y0 + 20], fill=(*color, 255))
        draw.text((x0 + 6, y0 + 4), str(i), fill=(255, 255, 255, 255))
    img.save(out_path)
    cert.overlay_path = out_path
    return out_path


def to_pdf(cert: Certificate, path: str) -> str:
    """A4 한 장짜리 검사 성적서. reportlab 내장 한글 CID 폰트를 쓴다."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.pdfmetrics import registerFont
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = "HYGothic-Medium"
    registerFont(UnicodeCIDFont(font))
    base = ParagraphStyle("b", fontName=font, fontSize=9.5, leading=14)
    small = ParagraphStyle("s", parent=base, fontSize=8, leading=11, textColor=colors.grey)
    h1 = ParagraphStyle("h1", parent=base, fontSize=18, leading=24)
    h2 = ParagraphStyle("h2", parent=base, fontSize=11, leading=16, spaceBefore=8, spaceAfter=3)
    tone = colors.HexColor("#c2410c") if cert.needs_human else colors.HexColor("#b91c1c")
    verdict = ParagraphStyle("v", parent=base, fontSize=15, leading=20, textColor=tone)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=16 * mm, bottomMargin=14 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm, title=f"검사 성적서 {cert.cert_id}")
    info = Table([
        ["성적서 번호", cert.cert_id, "발행", cert.issued],
        ["검사 이미지", cert.image_name, "모델", cert.model_version],
    ], colWidths=[24 * mm, 52 * mm, 16 * mm, 82 * mm])
    info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey), ("TEXTCOLOR", (2, 0), (2, -1), colors.grey),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
    ]))

    right = [Paragraph("판정", small), Paragraph(cert.verdict, verdict), Spacer(1, 3 * mm),
             Paragraph("결함 종류", small), Paragraph(f"{cert.defect_ko} · 확신도 {cert.confidence:.0%}", base),
             Spacer(1, 3 * mm), Paragraph("판정 근거", small)]
    right += [Paragraph(f"· {r}", base) for r in cert.reasons]
    if cert.overlay_path and os.path.exists(cert.overlay_path):
        left = RLImage(cert.overlay_path, width=78 * mm, height=78 * mm)
    else:
        left = Paragraph("이미지 없음", base)
    body = Table([[left, right]], colWidths=[82 * mm, 92 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    flow = [Paragraph("검사 성적서", h1), Spacer(1, 2 * mm), info, Spacer(1, 5 * mm), body]
    if cert.boxes:
        rows = [["번호", "종류", "검출 점수", "위치(가로 × 세로, 이미지 대비)"]]
        for i, b in enumerate(cert.boxes, 1):
            x0, y0, x1, y1 = b.xyxy
            rows.append([str(i), KO.get(b.cls, b.cls), f"{b.score:.2f}",
                         f"왼쪽 위 ({x0:.0%}, {y0:.0%}) · 크기 {x1 - x0:.0%} × {y1 - y0:.0%}"])
        t = Table(rows, colWidths=[14 * mm, 46 * mm, 22 * mm, 92 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ]))
        flow += [Paragraph("결함 위치", h2), t]
    if cert.criteria:
        flow.append(Paragraph(f"판정 기준 ({cert.sop_id})", h2))
        flow += [Paragraph(f"· {c}", base) for c in cert.criteria]
    if cert.actions:
        flow.append(Paragraph(f"조치 ({cert.sop_id})" if cert.sop_id else "조치", h2))
        flow += [Paragraph(f"{i}. {a}", base) for i, a in enumerate(cert.actions, 1)]
    flow += [Spacer(1, 8 * mm),
             Paragraph("판정 기준과 조치는 처리 지침 문서 원문에서 발췌했습니다. 길이·깊이 기준의 충족 여부는 "
                       "실측 치수가 필요하므로 이 성적서가 판정하지 않습니다.", small)]
    doc.build(flow)
    return path
