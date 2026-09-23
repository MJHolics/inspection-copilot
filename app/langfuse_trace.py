"""Langfuse 계측 — `app/trace.py`(자체 JSONL 트레이서)와 나란히 붙인다.

이 프로젝트는 이미 요청 단위 구조화 로깅(JSONL)과 자체 운영 대시보드를 갖고 있다.
Langfuse는 업계 표준 LLM 관측 도구라 그 자체와 실제로 비교해볼 가치가 있다 — 이 모듈은
자체 트레이서를 대체하지 않고 **같은 요청을 Langfuse에도 함께 보낸다**(옵트인).

키가 없으면(`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` 미설정) `enabled()`가 False라
어떤 코드 경로도 안 걸린다. `langfuse` 패키지 자체가 미설치라도 동일(지연 임포트).

SDK는 v4(OTel 기반)를 쓴다 — `.trace()/.span()/.generation()` 같은 구버전 메서드는 없고,
`start_as_current_observation(as_type=...)` 컨텍스트 매니저로 현재 컨텍스트에 중첩된다.
그래서 여기 API는 "trace 객체를 들고 다니며 나중에 append"가 아니라
**컨텍스트 매니저를 그대로 with에 쓰는** 형태다 — supervisor.handle()처럼 한 스레드 안에서
동기로 끝나는 요청에 잘 맞는다.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from . import config

_client = None
_import_failed = False


def enabled() -> bool:
    global _import_failed
    if _import_failed:
        return False
    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        return False
    try:
        import langfuse  # noqa: F401
    except ImportError:
        _import_failed = True
        return False
    return True


def _get_client():
    global _client
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            base_url=config.LANGFUSE_HOST,
        )
    return _client


@contextmanager
def request_span(name: str, request_text: str) -> Iterator[None]:
    """요청 1건을 감싸는 최상위 span. 비활성이면 그냥 아무 것도 안 하고 지나간다."""
    if not enabled():
        yield
        return
    client = _get_client()
    with client.start_as_current_observation(as_type="span", name=name, input={"request": request_text}):
        yield
    if config.LANGFUSE_FLUSH_EACH:
        client.flush()


def flush() -> None:
    """남은 배치를 전송(프로세스 종료 전 호출). 비활성이면 no-op."""
    if enabled() and _client is not None:
        _client.flush()


def update_current_span(**fields) -> None:
    """현재 활성 span에 필드를 갱신(비활성이면 no-op)."""
    if not enabled():
        return
    _get_client().update_current_span(**fields)


def update_current_generation(**fields) -> None:
    """현재 활성 generation에 필드를 갱신(비활성이면 no-op)."""
    if not enabled():
        return
    _get_client().update_current_generation(**fields)


@contextmanager
def step_span(agent: str) -> Iterator[None]:
    """서브에이전트 한 단계(StepRecord 하나에 대응)를 감싸는 중첩 span."""
    if not enabled():
        yield
        return
    client = _get_client()
    with client.start_as_current_observation(as_type="span", name=agent):
        yield


@contextmanager
def generation_span(name: str, model: str, system: str, user: str) -> Iterator[None]:
    """LLM 호출 1건(app/llm.py LLM.complete)을 감싸는 generation span."""
    if not enabled():
        yield
        return
    client = _get_client()
    with client.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    ):
        yield
