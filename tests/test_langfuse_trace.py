"""langfuse_trace — 키가 없으면 완전한 no-op, 요청마다 flush 여부는 설정을 따른다.

실제 Langfuse 서버·패키지 없이 돌도록 클라이언트를 가짜로 바꿔 끼운다.
"""
from __future__ import annotations

from contextlib import contextmanager

from app import config, langfuse_trace


class _FakeClient:
    def __init__(self) -> None:
        self.flushes = 0
        self.spans: list[str] = []

    @contextmanager
    def start_as_current_observation(self, as_type: str, name: str, **_):
        self.spans.append(f"{as_type}:{name}")
        yield

    def flush(self) -> None:
        self.flushes += 1

    def update_current_span(self, **_) -> None:
        pass


def _enable(monkeypatch, flush_each: bool) -> _FakeClient:
    fake = _FakeClient()
    monkeypatch.setattr(langfuse_trace, "enabled", lambda: True)
    monkeypatch.setattr(langfuse_trace, "_client", fake)
    monkeypatch.setattr(config, "LANGFUSE_FLUSH_EACH", flush_each)
    return fake


def test_disabled_without_keys(monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", "")
    assert langfuse_trace.enabled() is False
    with langfuse_trace.request_span("supervisor.handle", "q"):
        with langfuse_trace.step_span("knowledge"):
            langfuse_trace.update_current_span(output={"ok": True})
    langfuse_trace.flush()  # 예외 없이 지나가야 한다


def test_flush_each_request(monkeypatch):
    fake = _enable(monkeypatch, flush_each=True)
    for _ in range(3):
        with langfuse_trace.request_span("supervisor.handle", "q"):
            with langfuse_trace.step_span("knowledge"):
                pass
    assert fake.flushes == 3
    assert fake.spans.count("span:supervisor.handle") == 3
    assert fake.spans.count("span:knowledge") == 3


def test_batch_mode_does_not_flush_per_request(monkeypatch):
    fake = _enable(monkeypatch, flush_each=False)
    for _ in range(3):
        with langfuse_trace.request_span("supervisor.handle", "q"):
            pass
    assert fake.flushes == 0  # 요청 경로에서는 전송하지 않는다
    langfuse_trace.flush()
    assert fake.flushes == 1  # 종료 시 한 번
