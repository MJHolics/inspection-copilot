"""제공자 무관 LLM 클라이언트 — Gemini(무료 티어) 기본, Anthropic·OpenAI 옵션.

`nl2sql-analytics-agent/app/llm.py` 패턴 재사용. 실제 쓰는 제공자 SDK만 설치하면 된다.
키가 없으면 호출 시점에 친절한 RuntimeError를 던지므로, 서브에이전트는 이를 잡아
needs_human/에러로 흘려보낸다(키 없는 환경에서도 라우팅·트레이싱은 동작).
"""
from __future__ import annotations

import os

from . import config


def _detect_provider() -> str:
    p = config.LLM_PROVIDER.lower()
    if p != "auto":
        return p
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError(
        "LLM API 키가 없습니다. GEMINI_API_KEY(무료: aistudio.google.com) 또는 "
        "ANTHROPIC_API_KEY / OPENAI_API_KEY 중 하나를 설정하세요."
    )


class LLM:
    def __init__(self) -> None:
        self.provider = _detect_provider()
        self.model = config.LLM_MODEL[self.provider]
        self._client = None  # 지연 초기화

    def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        """system+user 프롬프트로 한 번 호출하고 텍스트만 반환. 429는 잠시 대기 후 재시도."""
        fn = {"gemini": self._gemini, "anthropic": self._anthropic, "openai": self._openai}.get(
            self.provider
        )
        if fn is None:
            raise ValueError(f"알 수 없는 provider: {self.provider}")
        last: Exception | None = None
        for _ in range(3):
            try:
                return fn(system, user, temperature)
            except Exception as e:
                s = str(e)
                if "429" not in s and "RESOURCE_EXHAUSTED" not in s and "rate limit" not in s.lower():
                    raise
                import re
                import time

                m = re.search(r"retryDelay\D+(\d+)", s)
                time.sleep(min(int(m.group(1)) if m else 5, 30))
                last = e
        raise last  # type: ignore[misc]

    def _gemini(self, system: str, user: str, temperature: float) -> str:
        if self._client is None:
            from google import genai

            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            self._client = genai.Client(api_key=key)
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature),
        )
        return (resp.text or "").strip()

    def _anthropic(self, system: str, user: str, temperature: float) -> str:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()

    def _openai(self, system: str, user: str, temperature: float) -> str:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return (resp.choices[0].message.content or "").strip()
