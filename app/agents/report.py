"""Report 에이전트 — 앞 에이전트 결과(context)를 구조화 검사 리포트로 종합한다.

요약·발견·권고·종합신뢰도·사람검토 배지를 담은 리포트를 만든다. 기본 산출물은 markdown(의존성
없음)이고, reportlab이 있고 출력 경로가 주어지면 PDF도 생성한다(없으면 markdown만, 안전 폴백).
종합 단계라 라우팅의 마지막에 온다. 불확실성은 입력 에이전트가 보유하므로 report 자체는 결정적.
"""
from __future__ import annotations

from ..reporting import build_report, to_markdown, to_pdf
from .base import AgentRequest, AgentResult, BaseAgent, Evidence


class ReportAgent(BaseAgent):
    name = "report"
    description = (
        "여러 에이전트의 결과를 종합해 구조화된 검사 리포트(요약·발견·권고·신뢰도)를 만든다. "
        "'리포트/보고서/정리해줘' 요청이거나 여러 단계 결과를 합쳐야 할 때 마지막에 호출한다."
    )
    keywords = ("리포트", "보고서", "정리", "요약해", "report", "pdf", "문서로")

    def __init__(self, pdf_path: str | None = None) -> None:
        # pdf_path가 주어지면 PDF도 시도(reportlab 필요). None이면 markdown만.
        self.pdf_path = pdf_path

    def run(self, req: AgentRequest) -> AgentResult:
        # report 자신은 제외하고 앞 단계 결과만 종합.
        records = {k: v for k, v in req.context.items() if k != self.name and isinstance(v, dict)}
        report = build_report(req.text, records)
        markdown = to_markdown(report)

        pdf_path = None
        pdf_error = None
        if self.pdf_path:
            try:
                pdf_path = to_pdf(report, self.pdf_path)
            except ImportError:
                pdf_error = "reportlab 미설치 — markdown만 생성"
            except Exception as e:  # 폰트/렌더 실패 등도 markdown으로 폴백
                pdf_error = f"PDF 생성 실패({e}) — markdown만 생성"

        n = len(records)
        summary = f"{n}개 에이전트 결과 종합(종합신뢰도 {report.overall_confidence:.2f})."
        if report.needs_human:
            summary += " 사람 검토 권고."
        if pdf_path:
            summary += f" PDF: {pdf_path}"
        elif pdf_error:
            summary += f" ({pdf_error})"

        return AgentResult(
            agent=self.name, ok=True, summary=summary,
            evidence=[Evidence(source="report", detail=f"종합 입력: {list(records.keys())}")],
            confidence=1.0,  # 종합 자체는 결정적
            needs_human=report.needs_human,  # 입력의 사람검토 신호를 리포트에 전파
            data={
                "sections": list(records.keys()),
                "markdown": markdown,
                "pdf_path": pdf_path,
                "overall_confidence": report.overall_confidence,
                "recommendation": report.recommendation,
            },
        )
