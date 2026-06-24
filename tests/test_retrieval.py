"""검색 베이스라인 테스트 — 코퍼스 로드 + TF-IDF 코사인 관련성. 오프라인."""
from __future__ import annotations

from app.retrieval import Chunk, KeywordRetriever, load_corpus, make_grounding_retriever, tokenize


def test_tokenize_drops_single_korean():
    toks = tokenize("스크래치 a 가 SOP-1")
    assert "스크래치" in toks and "sop" in toks
    assert "가" not in toks  # 길이1 한글 노이즈 제외


def test_corpus_loads():
    chunks = load_corpus()
    assert len(chunks) >= 4
    assert any("scratch" in c.source for c in chunks)


def test_relevant_doc_ranks_first():
    r = KeywordRetriever(load_corpus())
    hits = r.search("스크래치 결함 처리 절차와 롤러 점검")
    assert hits[0].chunk.source == "scratches"
    assert hits[0].score > hits[-1].score


def test_offtopic_low_score():
    r = KeywordRetriever(load_corpus())
    hits = r.search("점심 메뉴 추천 날씨")
    assert hits[0].score < 0.06  # 근거 게이트 임계 아래


def test_identical_text_high_similarity():
    c = Chunk(source="x", title="t", text="압연 온도 냉각 균열", tokens=tokenize("압연 온도 냉각 균열"))
    r = KeywordRetriever([c, Chunk("y", "t2", "전혀 다른 내용 데이터", tokenize("전혀 다른 내용 데이터"))])
    hits = r.search("압연 온도 냉각 균열")
    assert hits[0].chunk.source == "x" and hits[0].score > 0.9


def test_grounding_factory_tfidf_is_lightweight():
    # tfidf(기본)는 (None, None) → KnowledgeAgent 경량 기본 사용, 무거운 import 없음.
    retriever, tau = make_grounding_retriever("tfidf")
    assert retriever is None and tau is None


def test_grounding_factory_follows_config(monkeypatch):
    # name 미지정이면 config.GROUNDING_RETRIEVER를 따른다(기본 tfidf).
    import app.config as cfg
    monkeypatch.setattr(cfg, "GROUNDING_RETRIEVER", "tfidf", raising=False)
    assert make_grounding_retriever() == (None, None)
