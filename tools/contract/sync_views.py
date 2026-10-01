"""비교 전략 A(타입 없음)·B(손으로 쓴 타입)의 화면 코드를 앱 컴포넌트에서 다시 만든다.

세 전략의 렌더 코드는 같아야 공정하다 — 다른 건 타입 출처뿐. 앱 컴포넌트(web/src/views/ResultView.tsx)를
고치면 run_contract_bench.py가 실행 전에 이 스크립트로 복사본을 갱신한다.
"""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
IMP = 'import type { InspectResponse, RouterName } from "../api/types";'


def sync() -> None:
    src = (WEB / "src" / "views" / "ResultView.tsx").read_text(encoding="utf-8")
    assert IMP in src, "앱 컴포넌트의 타입 import 줄이 바뀌었다 — sync_views.py를 맞출 것"
    out = WEB / "bench" / "views"
    out.mkdir(parents=True, exist_ok=True)
    head = "// 자동 생성(tools/contract/sync_views.py) — 직접 고치지 말 것. 렌더 코드는 src/views/ResultView.tsx와 동일\n"
    (out / "manual.tsx").write_text(
        head + src.replace(IMP, '// 전략 B: 손으로 쓴 타입\nimport type { InspectResponse, RouterName } from "../manual-types";'),
        encoding="utf-8")
    un = src.replace(IMP, "// 전략 A: 타입 없음\ntype InspectResponse = any;\ntype RouterName = any;")
    un = un.replace("const ROUTER_LABEL: Record<RouterName, string>", "const ROUTER_LABEL: Record<string, string>")
    un = un.replace("data.agents.map((a) =>", "data.agents.map((a: any) =>")
    un = un.replace("a.evidence.map((e, i) =>", "a.evidence.map((e: any, i: number) =>")
    (out / "untyped.tsx").write_text(head + un, encoding="utf-8")


if __name__ == "__main__":
    sync()
    print("synced")
