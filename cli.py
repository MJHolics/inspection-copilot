"""CLI 진입점 — 자연어 질문(+선택 이미지)을 supervisor에 넣고 종합 답·라우팅을 출력.

사용:
  python cli.py "스크래치 결함 사진인데 어떻게 처리해야 해?"
  python cli.py "지난 달 스크래치 불량 몇 건이야?" --image path/to.jpg

  # 내구 실행 — 중간에 죽어도 같은 run-id로 다시 부르면 끝난 단계는 건너뛰고 이어서 한다
  python cli.py "이 결함 처리 절차 알려줘" --run-id job-42
  python cli.py "이 결함 처리 절차 알려줘" --run-id job-42     # 재개(또는 완료분 재생)
"""
from __future__ import annotations

import argparse

from app.service import get_durable_supervisor, get_supervisor


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspection Copilot — 멀티에이전트 검사 코파일럿")
    ap.add_argument("question", help="자연어 질문")
    ap.add_argument("--image", default=None, help="검사할 이미지 경로(선택)")
    ap.add_argument("--run-id", default=None,
                    help="내구 실행. 체크포인트를 runs/<run-id>.json에 남기고, 같은 값으로 다시 "
                         "부르면 끝난 단계를 건너뛰고 이어서 한다")
    ap.add_argument("--budget", type=float, default=None,
                    help="초 단위 시간 예산. 넘기면 남은 단계를 체크포인트에 두고 멈춘다(재개 가능)")
    ap.add_argument("--fsync", action="store_true",
                    help="체크포인트를 fsync까지 한다(전원 손실 대비). 기본은 프로세스 사망까지만 대비")
    args = ap.parse_args()

    if args.run_id:
        sup = get_durable_supervisor(args.run_id, fsync=args.fsync, budget_s=args.budget)
        res = sup.handle(args.question, image_path=args.image, run_id=args.run_id)
        print(res.answer)
        if sup.resumed_steps:
            print()
            print(f"[재개] 체크포인트 덕에 {sup.resumed_steps}단계를 건너뛰었습니다.")
        if sup.exhausted_steps:
            print(f"[주의] {sup.exhausted_steps}단계가 재시도를 소진해 사람 검토로 올렸습니다.")
    else:
        res = get_supervisor().handle(args.question, image_path=args.image)
        print(res.answer)


if __name__ == "__main__":
    main()
