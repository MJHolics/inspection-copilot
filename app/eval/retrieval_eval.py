"""검색 평가 — 임의 retriever의 Hit@k·MRR을 측정한다(순수 지표 + 러너).

retriever는 `.search(query, k) -> list[Hit]`(Hit.chunk.source, Hit.score)만 만족하면 된다 —
TF-IDF 베이스라인이든 dense(ko-sroberta)든 동일 지표로 비교한다. 검색 품질을 수치로 둬,
"어휘→의미 검색 교체"의 이득을 재현 가능하게 보여준다(multimodal_rag의 Hit Rate/MRR 서사).
"""
from __future__ import annotations


def reciprocal_rank(ranked_sources: list[str], gold: str) -> float:
    """정답이 처음 나오는 순위의 역수(없으면 0)."""
    for i, s in enumerate(ranked_sources, start=1):
        if s == gold:
            return 1.0 / i
    return 0.0


def evaluate(retriever, tasks: list[tuple[str, str]], k: int = 3) -> dict:
    """retriever를 태스크셋에 돌려 Hit@1·Hit@k·MRR 집계."""
    n = len(tasks)
    if n == 0:
        return {"count": 0}
    hit1 = hitk = 0
    mrr = 0.0
    for query, gold in tasks:
        hits = retriever.search(query, k=k)
        ranked = [h.chunk.source for h in hits]
        if ranked[:1] == [gold]:
            hit1 += 1
        if gold in ranked[:k]:
            hitk += 1
        mrr += reciprocal_rank(ranked, gold)
    return {
        "count": n,
        "hit@1": round(hit1 / n, 3),
        f"hit@{k}": round(hitk / n, 3),
        "mrr": round(mrr / n, 3),
    }


def _main() -> None:
    """TF-IDF 베이스라인(+가능하면 dense)으로 검색 평가를 출력·비교."""
    import json

    from ..retrieval import KeywordRetriever, load_corpus
    from .retrieval_tasks import RETRIEVAL_TASKS

    corpus = load_corpus()
    results = {"tfidf": evaluate(KeywordRetriever(corpus), RETRIEVAL_TASKS)}

    try:
        from ..retrieval_vector import DenseRetriever

        results["dense"] = evaluate(DenseRetriever(corpus), RETRIEVAL_TASKS)
    except Exception as e:  # sentence-transformers/모델 없으면 베이스라인만.
        results["dense"] = {"skipped": f"{type(e).__name__}: {e}"}

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
