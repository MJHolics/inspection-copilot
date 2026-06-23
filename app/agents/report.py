"""Report 에이전트 (P1 스텁).

앞선 에이전트들이 모은 근거(context)를 구조화 리포트(요약·발견·권고·신뢰도)로 합쳐
PDF로 만든다. 종합 단계라 보통 라우팅의 마지막에 온다. P2에서 reportlab으로 실제 PDF 생성.
"""
from __future__ import annotations

from .base import AgentRequest, AgentResult, BaseAgent, Evidence


class ReportAgent(BaseAgent):
    name = "report"
    description = (
        "여러 에이전트의 결과를 종합해 구조화된 검사 리포트(요약·발견·권고·신뢰도)를 만든다. "
        "'리포트/보고서/정리해줘' 요청이거나 여러 단계 결과를 합쳐야 할 때 마지막에 호출한다."
    )
    keywords = ("리포트", "보고서", "정리", "요약해", "report", "pdf", "문서로")

    def run(self, req: AgentRequest) -> AgentResult:
        # context에 쌓인 앞 에이전트 산출물을 집계한다(P1: 개수만, P2: 실제 PDF).
        prior = [k for k in req.context.keys()]
        # TODO(P2): reportlab으로 섹션화 PDF 생성 + 신뢰도/사람검토 배지.
        return AgentResult(
            agent=self.name,
            ok=True,
            summary=f"[스텁] {len(prior)}개 에이전트 결과({', '.join(prior) or '없음'}) 종합 리포트 예정(P2).",
            evidence=[Evidence(source="report", detail=f"종합 입력: {prior}", score=None)],
            confidence=1.0,  # 종합 자체는 결정적(불확실성은 입력 에이전트가 보유)
            needs_human=False,
            data={"sections": prior, "pdf_path": None, "stub": True},
        )
