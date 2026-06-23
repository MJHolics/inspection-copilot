"""Gradio 데모 — 검사 코파일럿 인터랙티브 UI(HF Spaces 진입점).

질문(+선택 이미지)을 넣으면 supervisor가 동적 라우팅 → 에이전트 실행 → 종합한다.
라우팅 경로·단계별 결과·종합 리포트·사람검토 배지를 보여준다.

LLM 키(GEMINI_API_KEY 등)가 있으면 Analytics가 실제 SQL을 생성·실행한다. 없으면 Analytics는
사람검토로 안전하게 멈추지만(Knowledge·Report·라우팅·트레이싱은 그대로 동작) 데모는 유효하다.
"""
from __future__ import annotations

import gradio as gr

from app.service import get_supervisor

EXAMPLES = [
    ["스크래치 결함은 어떤 절차로 처리해야 해?", None],
    ["라인별 불량 건수를 많은 순으로 알려줘", None],
    ["크레이징 처리 절차를 정리해서 보고서로 줘", None],
    ["오늘 점심 메뉴 추천해줘", None],  # 근거 부족 → 사람검토로 멈춤(가드레일 시연)
]


def run_inspection(question: str, image):
    if not question or not question.strip():
        return "질문을 입력하세요.", "", ""
    res = get_supervisor().handle(question, image_path=image)

    badge = "⚠️ 사람 검토 필요" if res.needs_human else "✅ 자동 판정"
    route = " → ".join(res.plan.steps)
    header = f"### {badge}\n**라우팅:** `{route}`  \n_{res.plan.reason}_"

    lines = []
    for r in res.results:
        flag = " ⚠️" if r.needs_human else ""
        conf = f" · 신뢰도 {r.confidence:.2f}" if r.confidence else ""
        lines.append(f"**{r.agent}**{conf}{flag}\n\n{r.summary}\n")
        for e in r.evidence:
            sc = f" ({e.score})" if e.score is not None else ""
            lines.append(f"> 근거: `{e.source}`{sc} — {e.detail}")
        lines.append("")
    steps_md = "\n".join(lines)

    report_md = next((r.data.get("markdown", "") for r in res.results if r.agent == "report"), "")
    return header, steps_md, report_md


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Inspection Copilot") as demo:
        gr.Markdown(
            "# 🔎 Inspection Copilot\n"
            "검증 가능한 멀티에이전트 품질 검사 코파일럿 — supervisor가 질문을 **동적 라우팅**해 "
            "비전·분석(NL2SQL)·지식(RAG)·리포트 에이전트로 보내고, 근거·신뢰도와 함께 답합니다. "
            "근거가 약하면 환각 대신 **사람 검토로 멈춥니다**."
        )
        with gr.Row():
            with gr.Column(scale=2):
                q = gr.Textbox(label="질문", placeholder="예: 스크래치 결함 처리 절차 알려줘", lines=2)
                img = gr.Image(label="검사 이미지(선택)", type="filepath")
                btn = gr.Button("실행", variant="primary")
                gr.Examples(EXAMPLES, inputs=[q, img])
            with gr.Column(scale=3):
                out_header = gr.Markdown(label="라우팅/판정")
                out_steps = gr.Markdown(label="단계별 결과")
        out_report = gr.Markdown(label="종합 리포트")
        btn.click(run_inspection, inputs=[q, img], outputs=[out_header, out_steps, out_report])
    return demo


if __name__ == "__main__":
    # 0.0.0.0:7860 — HF Spaces·Docker 컨테이너에서 외부 접근 가능하도록.
    build_demo().launch(server_name="0.0.0.0", server_port=7860)
