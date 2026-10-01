"""백엔드 계약 변경 9종 — 각 변경은 (변경된 Pydantic 모델, 응답 변환)의 쌍이다.

모든 변경은 **의미 보존**이다: 같은 정보를 다른 이름·타입·구조·단위로 보낸다. 그러므로 올바른 프론트라면
화면이 바뀌면 안 되고, 바뀌었는데 아무도 모르면 "조용한 오작동"이다. M8은 대조군(선택 필드 추가 — 무해해야 함).
M6(단위 변경)은 타입으로는 원리상 보이지 않는 변경이라 일부러 넣었다.
"""
# from __future__ import annotations 를 쓰지 않는다 — openapi_for의 지역 모델 주석을 FastAPI가 문자열로 못 푼다
import copy
from typing import Literal, Optional

from pydantic import BaseModel, create_model

from app.schemas import AgentOut, Evidence, InspectRequest, InspectResponse

MUTATIONS: dict[str, str] = {
    "M1": "필드 이름 변경 — agents[].confidence → trust_score",
    "M2": "필드 타입 변경 — latency_ms: int → str(\"22\")",
    "M3": "중첩 구조 변경 — agents[].evidence: list → {items, count}",
    "M4": "최상위 구조 변경 — router: str → routing: {mode}",
    "M5": "enum 표기 변경 — rule/llm/llm->rule → RULE/LLM/LLM_FALLBACK",
    "M6": "단위 변경(이름·타입 유지) — latency_ms 값을 초 단위로",
    "M7": "필드 이동 — report_markdown → report.markdown",
    "M8": "대조군: 선택 필드 추가 — trace_id",
    "M9": "요청 필드 이름 변경 — question → query",
}

_ENUM5 = {"rule": "RULE", "llm": "LLM", "llm->rule": "LLM_FALLBACK"}


def _resp_fields(**override) -> dict:
    """InspectResponse의 필드 정의를 create_model 형식으로 꺼내고 일부를 바꾼다(None이면 제거)."""
    fields = {n: (f.annotation, ...) for n, f in InspectResponse.model_fields.items()}
    for k, v in override.items():
        if v is None:
            fields.pop(k, None)
        else:
            fields[k] = v
    return fields


def models(name: str) -> tuple[type[BaseModel], type[BaseModel]]:
    """변경 name의 (요청 모델, 응답 모델). M0 = 변경 없음."""
    req, resp = InspectRequest, InspectResponse
    if name == "M1":
        agent = create_model("AgentOut", **{n: (f.annotation, ...) for n, f in AgentOut.model_fields.items()
                                             if n != "confidence"}, trust_score=(float, ...))
        resp = create_model("InspectResponse", **_resp_fields(agents=(list[agent], ...)))
    elif name == "M2":
        resp = create_model("InspectResponse", **_resp_fields(latency_ms=(Optional[str], ...)))
    elif name == "M3":
        ev = create_model("EvidenceList", items=(list[Evidence], ...), count=(int, ...))
        agent = create_model("AgentOut", **{n: (f.annotation, ...) for n, f in AgentOut.model_fields.items()
                                             if n != "evidence"}, evidence=(ev, ...))
        resp = create_model("InspectResponse", **_resp_fields(agents=(list[agent], ...)))
    elif name == "M4":
        routing = create_model("Routing", mode=(Literal["rule", "llm", "llm->rule"], ...))
        resp = create_model("InspectResponse", **_resp_fields(router=None, routing=(routing, ...)))
    elif name == "M5":
        resp = create_model("InspectResponse", **_resp_fields(router=(Literal["RULE", "LLM", "LLM_FALLBACK"], ...)))
    elif name == "M6":
        resp = create_model("InspectResponse", **_resp_fields(latency_ms=(Optional[float], ...)))
    elif name == "M7":
        report = create_model("Report", markdown=(Optional[str], ...))
        resp = create_model("InspectResponse", **_resp_fields(report_markdown=None, report=(report, ...)))
    elif name == "M8":
        resp = create_model("InspectResponse", **_resp_fields(trace_id=(Optional[str], None)))
    elif name == "M9":
        req = create_model("InspectRequest", query=(str, ...), image_path=(Optional[str], None))
    return req, resp


def transform(name: str, d: dict) -> dict:
    """변경 전 응답 d → 변경 후 백엔드가 보낼 응답(같은 정보)."""
    d = copy.deepcopy(d)
    if name == "M1":
        for a in d["agents"]:
            a["trust_score"] = a.pop("confidence")
    elif name == "M2":
        d["latency_ms"] = None if d["latency_ms"] is None else str(d["latency_ms"])
    elif name == "M3":
        for a in d["agents"]:
            a["evidence"] = {"items": a["evidence"], "count": len(a["evidence"])}
    elif name == "M4":
        d["routing"] = {"mode": d.pop("router")}
    elif name == "M5":
        d["router"] = _ENUM5[d["router"]]
    elif name == "M6":
        d["latency_ms"] = None if d["latency_ms"] is None else d["latency_ms"] / 1000
    elif name == "M7":
        d["report"] = {"markdown": d.pop("report_markdown")}
    elif name == "M8":
        d["trace_id"] = "t-0001"
    return d


def openapi_for(name: str) -> dict:
    """변경된 모델로 FastAPI 앱을 만들어 OpenAPI를 뽑는다(백엔드가 모델을 바꾸고 재배포한 상황)."""
    from fastapi import FastAPI

    req_m, resp_m = models(name)
    app = FastAPI(title="Inspection Copilot", version="0.1.0")

    @app.post("/inspect", response_model=resp_m)
    def inspect(req: req_m):  # type: ignore[valid-type]  # noqa: ARG001
        raise NotImplementedError

    return app.openapi()
