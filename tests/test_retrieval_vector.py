"""Dense retriever 테스트 — sentence-transformers 있을 때만(없으면 skip).

dense가 패러프레이즈 질의에서 TF-IDF 베이스라인 이상임을 검증(의미검색 이득). torch/모델이 필요해
CI·경량 venv에서는 자동 skip. 모델 다운로드를 피하려 오프라인 환경변수로 캐시만 사용.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("sentence_transformers")

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.eval.retrieval_eval import evaluate  # noqa: E402
from app.eval.retrieval_tasks import RETRIEVAL_TASKS  # noqa: E402
from app.retrieval import KeywordRetriever, load_corpus  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


def test_dense_search_returns_hits(corpus):
    from app.retrieval_vector import DenseRetriever

    r = DenseRetriever(corpus)
    hits = r.search("긁힌 자국 처리 절차", k=3)
    assert len(hits) == 3
    assert all(0.0 <= h.score <= 1.0001 for h in hits)


def test_dense_beats_or_matches_tfidf(corpus):
    from app.retrieval_vector import DenseRetriever

    tfidf = evaluate(KeywordRetriever(corpus), RETRIEVAL_TASKS, k=3)
    dense = evaluate(DenseRetriever(corpus), RETRIEVAL_TASKS, k=3)
    # 의미검색이 어휘검색 이상이어야(패러프레이즈 이득). MRR로 비교.
    assert dense["mrr"] >= tfidf["mrr"]
    assert dense["hit@3"] >= tfidf["hit@3"]
