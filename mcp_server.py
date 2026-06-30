"""InspectOps MCP 서버 — 검사 코파일럿의 검증된 도구를 Model Context Protocol로 노출.

어떤 MCP 클라이언트(Claude Desktop·IDE 등)에서도 이 검사 도구를 표준 프로토콜로 호출할 수 있다.
핵심은 **검증 척추가 도구에 함께 실린다**는 점 — SOP 검색은 인젝션 가드 + 근거 거리 게이트를
통과하지 못하면 needs_human을 돌려준다. 도구 로직은 코파일럿의 기존(테스트된) 순수 모듈을 재사용.

실행: python mcp_server.py    (stdio 전송 — MCP 클라이언트가 이 명령을 등록해 사용)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("inspectops")

_retriever = None  # SOP 코퍼스 인덱스(지연 생성·캐시)


def _get_retriever():
    global _retriever
    if _retriever is None:
        from app.retrieval import KeywordRetriever, load_corpus
        _retriever = KeywordRetriever(load_corpus())
    return _retriever


@mcp.tool()
def check_prompt_injection(text: str) -> dict:
    """질의가 프롬프트 인젝션/시스템 탈취 시도인지 판정한다(검색 거리와 직교한 안전 가드)."""
    from app.guard import is_injection

    inj = is_injection(text)
    return {"is_injection": inj, "action": "block(needs_human)" if inj else "allow"}


@mcp.tool()
def search_inspection_sop(query: str, k: int = 3) -> dict:
    """검사 표준·SOP에서 근거를 검색한다. 인젝션이거나 근거가 약하면 사람검토로 멈춘다(환각 방지).

    반환: grounded(bool)·needs_human(bool)·top_source·evidence[{source,title,score}].
    """
    from app.agents.knowledge import GROUNDING_TAU
    from app.guard import is_injection

    if is_injection(query):
        return {"grounded": False, "needs_human": True,
                "reason": "prompt_injection", "evidence": []}

    hits = _get_retriever().search(query, k=k)
    top = hits[0].score if hits else 0.0
    evidence = [{"source": h.chunk.source, "title": h.chunk.title, "score": round(h.score, 4)}
                for h in hits if h.score > 0]
    if not hits or top < GROUNDING_TAU:
        return {"grounded": False, "needs_human": True,
                "reason": "weak_evidence", "evidence": evidence}
    return {"grounded": True, "needs_human": False,
            "top_source": hits[0].chunk.source, "evidence": evidence}


@mcp.tool()
def validate_sql(sql: str) -> dict:
    """분석 SQL이 안전한 조회(SELECT 전용)인지 검증한다. 쓰기·삭제·생성 구문은 거부."""
    from app.sqlutils import is_safe_select

    safe, why = is_safe_select(sql)
    return {"ok": safe, "error": None if safe else why}


if __name__ == "__main__":
    mcp.run()  # stdio 전송
