"""CLI 진입점 — 자연어 질문(+선택 이미지)을 supervisor에 넣고 종합 답·라우팅을 출력.

사용:
  python cli.py "스크래치 결함 사진인데 어떻게 처리해야 해?"
  python cli.py "지난 달 스크래치 불량 몇 건이야?" --image path/to.jpg
"""
from __future__ import annotations

import argparse

from app.supervisor import Supervisor


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspection Copilot — 멀티에이전트 검사 코파일럿")
    ap.add_argument("question", help="자연어 질문")
    ap.add_argument("--image", default=None, help="검사할 이미지 경로(선택)")
    args = ap.parse_args()

    sup = Supervisor()
    res = sup.handle(args.question, image_path=args.image)
    print(res.answer)


if __name__ == "__main__":
    main()
