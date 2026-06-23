"""검색 평가 지표 테스트 — Hit@k·MRR 순수함수 + TF-IDF 베이스라인 스모크. 오프라인."""
from __future__ import annotations

from app.eval.retrieval_eval import evaluate, reciprocal_rank
from app.eval.retrieval_tasks import RETRIEVAL_TASKS
from app.retrieval import KeywordRetriever, load_corpus


def test_reciprocal_rank():
    assert reciprocal_rank(["a", "b", "c"], "a") == 1.0
    assert reciprocal_rank(["a", "b", "c"], "b") == 0.5
    assert reciprocal_rank(["a", "b"], "z") == 0.0


class _FakeHitChunk:
    def __init__(self, source):
        self.source = source


class _FakeHit:
    def __init__(self, source, score):
        self.chunk = _FakeHitChunk(source)
        self.score = score


class _FakeRetriever:
    def __init__(self, ranking):
        self.ranking = ranking  # source 순위 리스트

    def search(self, query, k=3):
        return [_FakeHit(s, 1.0 - i * 0.1) for i, s in enumerate(self.ranking[:k])]


def test_evaluate_perfect():
    r = _FakeRetriever(["scratches", "x", "y"])
    s = evaluate(r, [("q", "scratches")], k=3)
    assert s["hit@1"] == 1.0 and s["mrr"] == 1.0


def test_evaluate_rank2():
    r = _FakeRetriever(["x", "scratches", "y"])
    s = evaluate(r, [("q", "scratches")], k=3)
    assert s["hit@1"] == 0.0 and s["hit@3"] == 1.0 and s["mrr"] == 0.5


def test_tfidf_baseline_on_real_tasks():
    s = evaluate(KeywordRetriever(load_corpus()), RETRIEVAL_TASKS, k=3)
    assert s["count"] == len(RETRIEVAL_TASKS)
    # 직접매칭 5건은 TF-IDF도 잡으므로 hit@3는 충분히 높아야(회귀 가드).
    assert s["hit@3"] >= 0.5
