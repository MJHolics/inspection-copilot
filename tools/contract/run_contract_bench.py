"""계약 변경 실험 — 백엔드 응답 모델이 바뀌었을 때 프론트엔드는 어디서 알아채는가.

  python tools/contract/run_contract_bench.py            # → results/contract/contract_bench.json

변경 9종(tools/contract/mutations.py) × 전략 4종:
  A untyped   타입 없음(any). 빌드는 항상 통과, 실행 중에 드러나거나 안 드러난다
  B manual    손으로 쓴 타입. 백엔드와 연결 안 됨 → 빌드는 항상 통과
  C generated OpenAPI에서 타입을 다시 생성(`openapi-typescript`) 후 `tsc` — 빌드 단계에서 잡는가
  D zod       B + 응답 경계에서 zod 런타임 검증 — 프론트를 다시 빌드하지 않고 백엔드만 먼저 배포된 경우
응답 표본: 골든 15 + 적대적 13문항의 실제 응답(결정적·오프라인). 변경 응답은 변경된 모델로 검증해 "그 백엔드가
실제로 보낼 수 있는 응답"임을 확인한 뒤에만 쓴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def _npx(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([NPX, *args], cwd=WEB, capture_output=True, text=True, encoding="utf-8", shell=False)


def baseline_responses() -> list[dict]:
    from app.eval.adversarial_tasks import ADVERSARIAL
    from app.eval.tasks import GOLDEN
    from app.service import get_supervisor, result_to_dict

    return [result_to_dict(get_supervisor().handle(t.question, image_path=t.image_path)) for t in GOLDEN + ADVERSARIAL]


def typecheck_generated(openapi: dict) -> dict:
    """전략 C: 변경된 OpenAPI로 타입을 재생성하고 앱 코드(src/)를 tsc로 검사한다."""
    work = WEB / "bench" / ".work"
    work.mkdir(parents=True, exist_ok=True)
    spec = work / "openapi.json"
    spec.write_text(json.dumps(openapi, ensure_ascii=False), encoding="utf-8")
    gen = WEB / "src" / "api" / "generated.ts"
    backup = gen.read_text(encoding="utf-8")
    try:
        # 상대 경로로 넘긴다 — 절대 경로의 한글 폴더명을 openapi-typescript가 URL 인코딩해 파일을 못 찾는다
        g = _npx("openapi-typescript", "bench/.work/openapi.json", "-o", "src/api/generated.ts")
        if g.returncode != 0:
            raise RuntimeError(g.stderr)
        t = _npx("tsc", "--noEmit", "-p", "tsconfig.app.json")
        errs = [ln for ln in t.stdout.splitlines() if re.search(r"error TS\d+", ln)]
        files = sorted({ln.split("(")[0] for ln in errs})
        return {"build_errors": len(errs), "files": files, "first": errs[0][:220] if errs else None}
    finally:
        gen.write_text(backup, encoding="utf-8")


def runtime(pairs: list[dict], request_ok: bool) -> dict:
    work = WEB / "bench" / ".work"
    work.mkdir(parents=True, exist_ok=True)
    fx = work / "fixtures.json"
    fx.write_text(json.dumps({"request_ok": request_ok, "pairs": pairs}, ensure_ascii=False), encoding="utf-8")
    r = _npx("tsx", "bench/runtime.tsx", "bench/.work/fixtures.json")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> int:
    from mutations import MUTATIONS, models, openapi_for, transform
    from sync_views import sync

    sync()  # 비교 전략의 화면 코드를 앱 컴포넌트와 같게 맞춘 뒤 잰다

    base = baseline_responses()
    print(f"응답 표본 {len(base)}건")
    rows = {}
    for name in ["M0", *MUTATIONS]:
        req_m, resp_m = models(name)
        mutated = [transform(name, d) for d in base]
        for m in mutated:  # 변경된 백엔드가 실제로 보낼 수 있는 응답인지 확인
            resp_m.model_validate(m)
        try:  # 프론트가 보내는 요청 {question, image_path}를 변경된 백엔드가 받는가
            req_m.model_validate({"question": "q", "image_path": None})
            request_ok = True
        except Exception:
            request_ok = False
        build = typecheck_generated(openapi_for(name))
        rt = runtime([{"baseline": b, "mutated": m} for b, m in zip(base, mutated)], request_ok)
        rows[name] = {"desc": MUTATIONS.get(name, "변경 없음(기준)"), "request_ok": request_ok,
                      "generated_build": build, "runtime": rt["counts"], "silent_example": rt["silent_example"]}
        c = rt["counts"]
        print(f"{name} build_err={build['build_errors']:>2} | " + " | ".join(
            f"{s}: " + ",".join(f"{k}={v}" for k, v in c[s].items() if v) for s in c))

    out = ROOT / "results" / "contract"
    out.mkdir(parents=True, exist_ok=True)
    (out / "contract_bench.json").write_text(json.dumps({"n_responses": len(base), "rows": rows},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out / 'contract_bench.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
