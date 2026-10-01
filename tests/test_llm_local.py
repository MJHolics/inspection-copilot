"""온프레미스 제공자 선택 — LOCAL_LLM_BASE_URL이 있으면 auto에서 외부 API보다 먼저 고른다."""
from app import config, llm


def test_local_wins_auto_even_with_cloud_key(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(config, "LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    assert llm._detect_provider() == "local"


def test_no_local_url_falls_back_to_cloud_key(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(config, "LOCAL_LLM_BASE_URL", "")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    assert llm._detect_provider() == "gemini"
