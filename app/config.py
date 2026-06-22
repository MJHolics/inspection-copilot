"""중앙 설정. 환경변수로 덮어쓸 수 있다(.env 지원).

LLM은 provider 무관 — Gemini 무료 티어 기본. 검사 도메인 클래스는 NEU 6종을 1차로 쓴다.
"""
from __future__ import annotations

import os


def _load_dotenv() -> None:
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    for raw in open(path, encoding="utf-8-sig"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# --- LLM ---
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto")  # gemini | anthropic | openai | auto
LLM_MODEL: dict[str, str] = {
    "gemini": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
}

# --- 검사 도메인 ---
DEFECT_CLASSES: list[str] = [
    "crazing", "inclusion", "patches", "pitted_surface", "rolled-in_scale", "scratches",
]

# --- 트레이싱 ---
TRACE_FILE: str = os.getenv("TRACE_FILE", "")  # 비우면 stdout만
TRACE_ECHO: bool = os.getenv("TRACE_ECHO", "1") != "0"
