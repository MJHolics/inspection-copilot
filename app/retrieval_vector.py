"""Dense(의미) 검색 — sentence-transformers 임베딩 기반 retriever.

`KeywordRetriever`(TF-IDF)와 **동일한 `.search(query, k) -> list[Hit]` 프로토콜**을 만족해,
Knowledge 에이전트·검색 평가에서 그대로 교체할 수 있다. 기본 모델은 한국어 문장 임베딩
`jhgan/ko-sroberta-multitask`(검사 SOP가 한국어). BGE-M3 등 다국어 모델로 교체 가능
(`DenseRetriever(corpus, model_name="BAAI/bge-m3")`).

sentence-transformers/torch가 없으면 import 시 예외 → 호출부(Knowledge·retrieval_eval)는 이를
잡아 TF-IDF 베이스라인으로 폴백한다. 어휘 겹침이 적은 패러프레이즈 질의에서 TF-IDF를 앞선다.
"""
from __future__ import annotations

from .retrieval import Chunk, Hit, load_corpus

DEFAULT_MODEL = "jhgan/ko-sroberta-multitask"


class DenseRetriever:
    """문장 임베딩 코사인 검색. 코퍼스 임베딩은 생성 시 1회 인코딩해 캐시."""

    name = "dense"

    def __init__(self, chunks: list[Chunk] | None = None, model_name: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import SentenceTransformer  # 지연 import(무거운 선택 의존성)

        self.chunks = chunks if chunks is not None else load_corpus()
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        # 검색 대상은 본문(텍스트). normalize로 코사인 = 내적.
        self._emb = self._model.encode(
            [c.text for c in self.chunks], normalize_embeddings=True, convert_to_numpy=True
        )

    def search(self, query: str, k: int = 3) -> list[Hit]:
        import numpy as np

        q = self._model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
        scores = self._emb @ q  # 정규화돼 있으므로 코사인 유사도
        order = np.argsort(-scores)[:k]
        return [Hit(chunk=self.chunks[i], score=float(scores[i])) for i in order]
