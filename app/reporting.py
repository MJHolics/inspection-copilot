"""리포트 빌더 — 앞 에이전트 결과를 구조화 검사 리포트로 합친다.

`build_report`/`to_markdown`는 순수 함수라 오프라인 테스트된다(의존성 없음). `to_pdf`는 reportlab을
선택 사용하며, 미설치 시 ImportError를 올린다(에이전트는 이를 잡아 markdown 폴백). PDF는 reportlab
내장 한글 CID 폰트(HYSMyeongJo-Medium)를 써서 외부 폰트 파일 없이 한국어를 렌더한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Section:
    agent: str
    summary: str
    confidence: float
    needs_human: bool
    ok: bool


@dataclass
class ReportDoc:
    title: str
    generated_ts: str
    question: str
    sections: list[Section] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    recommendation: str = ""
    overall_confidence: float = 1.0
    needs_human: bool = False


def build_report(question: str, records: dict[str, dict]) -> ReportDoc:
    """records = {에이전트명: {summary, confidence, needs_human, ok, data}} → 구조화 리포트.

    overall_confidence = 관여 에이전트 신뢰도의 최솟값(가장 약한 고리), needs_human은 OR.
    findings/recommendation은 결과에서 결정적으로 파생한다(환각 없음).
    """
    sections: list[Section] = []
    findings: list[str] = []
    confidences: list[float] = []
    needs_human = False

    for name, rec in records.items():
        conf = float(rec.get("confidence", 1.0))
        nh = bool(rec.get("needs_human", False))
        ok = bool(rec.get("ok", True))
        sections.append(Section(name, str(rec.get("summary", "")), conf, nh, ok))
        confidences.append(conf)
        needs_human = needs_human or nh
        if not ok:
            findings.append(f"{name}: 실패/미완료 — 결과를 신뢰할 수 없음")
        elif nh:
            findings.append(f"{name}: 신뢰도 낮음({conf:.2f}) — 사람 검토 필요")

    overall = min(confidences) if confidences else 1.0
    if needs_human:
        recommendation = "사람 검토 필요: 신뢰도가 낮거나 실패한 단계가 있어 자동 판정을 보류한다."
    elif not sections:
        recommendation = "종합할 입력이 없습니다."
    else:
        recommendation = "자동 판정 신뢰 가능: 모든 단계가 임계 이상으로 완료되었다."

    return ReportDoc(
        title="검사 종합 리포트",
        generated_ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        question=question,
        sections=sections,
        findings=findings or ["특이사항 없음"],
        recommendation=recommendation,
        overall_confidence=round(overall, 3),
        needs_human=needs_human,
    )


def to_markdown(report: ReportDoc) -> str:
    """리포트를 마크다운 문자열로(PDF 없이도 쓰는 기본 산출물)."""
    badge = "⚠ 사람 검토 필요" if report.needs_human else "✓ 자동 판정"
    lines = [
        f"# {report.title}",
        "",
        f"- 생성: {report.generated_ts}",
        f"- 질문: {report.question}",
        f"- 종합 신뢰도: {report.overall_confidence:.2f}  ·  판정: {badge}",
        "",
        "## 단계별 결과",
    ]
    for s in report.sections:
        flag = " ⚠" if s.needs_human else ""
        lines.append(f"- **{s.agent}**(신뢰도 {s.confidence:.2f}){flag}: {s.summary}")
    lines += ["", "## 발견"]
    lines += [f"- {f}" for f in report.findings]
    lines += ["", "## 권고", f"{report.recommendation}", ""]
    return "\n".join(lines)


def to_pdf(report: ReportDoc, path: str) -> str:
    """reportlab으로 PDF 생성(한글 CID 폰트). reportlab 미설치 시 ImportError."""
    import os

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.pdfmetrics import registerFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    styles = getSampleStyleSheet()
    for st in styles.byName.values():
        st.fontName = "HYSMyeongJo-Medium"

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    flow = [Paragraph(report.title, styles["Title"]), Spacer(1, 6 * mm)]
    md = to_markdown(report)
    for line in md.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            flow += [Spacer(1, 4 * mm), Paragraph(line[3:], styles["Heading2"])]
        elif line.strip():
            flow.append(Paragraph(line.lstrip("- ").replace("**", ""), styles["Normal"]))
    doc.build(flow)
    return path
