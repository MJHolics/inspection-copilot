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

# --- Langfuse(선택, 자체 트레이서와 병행) ---
# 키가 없으면 langfuse_trace.enabled()가 False라 아무 데도 안 걸린다 — 평소 실행엔 영향 없음.
LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
# 요청마다 flush(동기 전송)할지. 기본 0 = SDK 백그라운드 배치(종료 시 atexit flush).
# 실측(tools/bench_langfuse*.py): 요청마다 flush는 요청당 +57ms·처리량 절반·서버 다운 시 요청당 4초
# 정지. 배치는 +0.35ms·다운에도 무영향, 대가는 크래시 시 마지막 전송 주기분 유실(1초 주기 ≈8%).
# 그 구간은 자체 JSONL 트레이서(app/trace.py, 요청마다 파일에 즉시 기록)가 남긴다.
# 전송 주기는 SDK 환경변수 LANGFUSE_FLUSH_INTERVAL(기본 5초, 권장 1초)로 조절한다.
LANGFUSE_FLUSH_EACH: bool = os.getenv("LANGFUSE_FLUSH_EACH", "0") != "0"

# --- 그라운딩 검색기 ---
# tfidf = 경량 어휘검색(기본, HF Spaces 무의존). dense = 의미검색(ko-sroberta) — 동의어·
# 다국어·오프토픽을 분리(adversarial eval 실측). dense는 sentence-transformers 설치 필요.
GROUNDING_RETRIEVER: str = os.getenv("GROUNDING_RETRIEVER", "tfidf")  # tfidf | dense
GROUNDING_DENSE_MODEL: str = os.getenv("GROUNDING_DENSE_MODEL", "jhgan/ko-sroberta-multitask")
# dense 코사인 임계(캘리브): 정상/동의어 0.46~0.71, 오프토픽 0.18~0.31 사이에서 분리.
GROUNDING_DENSE_TAU: float = float(os.getenv("GROUNDING_DENSE_TAU", "0.40"))
