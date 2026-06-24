"""검색(retrieval) — 검사 SOP 코퍼스 로드 + TF-IDF 코사인 검색(순수 stdlib).

무거운 임베딩(BGE-M3) 없이도 도는 어휘 기반 베이스라인 retriever를 기본 제공한다. 결정적·
오프라인이라 단위테스트가 쉽다. 더 강한 의미 검색이 필요하면 `Retriever` 프로토콜(`.search`)을
만족하는 벡터 retriever(Chroma+BGE-M3)를 주입해 교체한다 — `multimodal_rag` 자산이 그 자리.

근거 거리 게이트: 최상위 유사도가 임계 미만이면 "관련 근거 부족"으로 신뢰도를 낮춰, Knowledge
에이전트가 needs_human으로 멈출 수 있게 한다(환각 대신 멈춤).
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs", "sop")

_TOKEN_RE = re.compile(r"[가-힣]+|[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """한글 음절열 + 영숫자 토큰. 길이 1 한글은 노이즈라 제외."""
    toks = _TOKEN_RE.findall(text.lower())
    return [t for t in toks if not (len(t) == 1 and "가" <= t <= "힣")]


@dataclass
class Chunk:
    source: str   # 파일명(SOP id)
    title: str    # 첫 헤딩
    text: str
    tokens: list[str] = field(default_factory=list)


def load_corpus(docs_dir: str = DOCS_DIR) -> list[Chunk]:
    """SOP 마크다운을 청크로 로드. 파일 1개 = 청크 1개(짧은 SOP라 문서 단위)."""
    chunks: list[Chunk] = []
    if not os.path.isdir(docs_dir):
        return chunks
    for name in sorted(os.listdir(docs_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(docs_dir, name)
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), name)
        chunks.append(Chunk(source=name[:-3], title=title, text=text, tokens=tokenize(text)))
    return chunks


def make_grounding_retriever(name: str | None = None):
    """그라운딩 retriever 팩토리 → (retriever | None, tau | None).

    name=None이면 config.GROUNDING_RETRIEVER를 따른다. tfidf는 (None, None)을 줘서
    KnowledgeAgent의 경량 기본(TF-IDF + GROUNDING_TAU)을 그대로 쓰게 한다. dense는 의미검색
    + 캘리브 tau를 돌려준다(무거운 sentence-transformers import는 이 경로에서만 발생).
    eval과 service가 같은 팩토리를 써 동작이 갈리지 않는다.
    """
    from . import config

    name = name or config.GROUNDING_RETRIEVER
    if name == "dense":
        from .retrieval_vector import DenseRetriever
        return DenseRetriever(load_corpus(), model_name=config.GROUNDING_DENSE_MODEL), \
            config.GROUNDING_DENSE_TAU
    return None, None


@dataclass
class Hit:
    chunk: Chunk
    score: float  # 코사인 유사도 0~1


class KeywordRetriever:
    """TF-IDF 코사인 검색(결정적·오프라인 베이스라인).

    `Retriever` 프로토콜 = `.search(query, k) -> list[Hit]`. 벡터 retriever로 교체 가능.
    """

    name = "tfidf"

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        n = max(1, len(chunks))
        df: Counter[str] = Counter()
        for c in chunks:
            df.update(set(c.tokens))
        # smoothed idf
        self.idf: dict[str, float] = {t: math.log((n + 1) / (df_t + 1)) + 1.0 for t, df_t in df.items()}
        self._vecs = [self._vectorize(c.tokens) for c in chunks]

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())

    def search(self, query: str, k: int = 3) -> list[Hit]:
        qvec = self._vectorize(tokenize(query))
        scored = [Hit(chunk=c, score=self._cosine(qvec, self._vecs[i])) for i, c in enumerate(self.chunks)]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]
