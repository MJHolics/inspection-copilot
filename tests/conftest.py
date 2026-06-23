"""테스트 격리 — LLM 키를 제거해 어떤 테스트도 실 네트워크를 타지 않게 한다.

Analytics 등 LLM 의존 에이전트는 키가 없으면 needs_human으로 안전히 멈추므로(가짜 LLM을
주입하는 테스트는 그 경로를 우회), 전 테스트가 결정적·오프라인으로 돈다.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
