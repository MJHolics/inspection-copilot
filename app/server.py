"""FastAPI 서빙 — 검사 코파일럿을 HTTP로 노출(서빙·관측성·eval 엔드포인트).

  GET  /health   헬스체크
  POST /inspect  {question, image_path?} → 라우팅·에이전트 결과·리포트·지연
  GET  /eval     골든셋 평가 지표(라우팅·그라운딩·게이트·e2e)

uvicorn으로 구동: `uvicorn app.server:app --host 0.0.0.0 --port 8000`
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .service import get_supervisor, result_to_dict

app = FastAPI(title="Inspection Copilot", version="0.1.0")


class InspectRequest(BaseModel):
    question: str
    image_path: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "inspection-copilot"}


@app.post("/inspect")
def inspect(req: InspectRequest) -> dict:
    res = get_supervisor().handle(req.question, image_path=req.image_path)
    return result_to_dict(res)


@app.get("/eval")
def eval_metrics() -> dict:
    # 지연 import — eval은 무겁지 않지만 서버 기동을 가볍게.
    from .eval.run_eval import run

    _, summary = run()
    return summary
