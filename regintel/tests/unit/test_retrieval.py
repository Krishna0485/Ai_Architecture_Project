from __future__ import annotations

import pytest

from regintel.config import Settings
from regintel.generation.prompts import PromptRegistry
from regintel.llm.gateway import build_gateway
from regintel.retrieval.base import (
    Chunk,
    MetadataFilter,
    Retriever,
    ScoredChunk,
    SecurityContext,
    reciprocal_rank_fusion,
)
from regintel.retrieval.bm25 import BM25Index, KeywordRetriever
from regintel.retrieval.embeddings import HashingEmbedder, cosine
from regintel.retrieval.factory import NAMED_CONFIGS, RetrievalConfig, build_pipeline
from regintel.retrieval.hybrid import HybridRetriever
from regintel.retrieval.query_rewrite import QueryRewriter
from regintel.retrieval.reranker import LexicalReranker
from regintel.retrieval.vector import InMemoryVectorStore, VectorRetriever

CTX = SecurityContext("acme", ("compliance",))


def c(cid: str, text: str, **md: str) -> Chunk:
    return Chunk(cid, text, {"section": cid, **md})


CHUNKS = [
    c("a", "Employers must provide twelve workweeks of family leave."),
    c("b", "Customer information must be encrypted at rest and in transit."),
    c("c", "Multi-factor authentication is required for every information system."),
    c("d", "Acme private escalation note.", tenant_id="acme", allowed_groups="compliance"),
    c("e", "Globex private escalation note.", tenant_id="globex", allowed_groups="compliance"),
    c("f", "Acme HR only note about leave.", tenant_id="acme", allowed_groups="hr"),
]


def test_rrf_matches_hand_computation() -> None:
    a, b, x = (ScoredChunk(Chunk(i, i), 0) for i in "abx")
    fused = reciprocal_rank_fusion([[a, b], [b, x]], k=60)
    scores = {s.chunk.id: s.score for s in fused}
    assert fused[0].chunk.id == "b"
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)


def test_security_context_visibility() -> None:
    by_id = {ch.id: ch for ch in CHUNKS}
    assert CTX.can_see(by_id["a"])  # public, "*"
    assert CTX.can_see(by_id["d"])
    assert not CTX.can_see(by_id["e"])  # other tenant
    assert not CTX.can_see(by_id["f"])  # same tenant, wrong group


def test_metadata_filter() -> None:
    ch = c("z", "t", jurisdiction="US-FED", act="X", source="s")
    assert MetadataFilter(jurisdiction="US-FED").matches(ch)
    assert not MetadataFilter(act="Y").matches(ch)


def test_hashing_embedder_is_normalised_and_deterministic() -> None:
    e = HashingEmbedder(256)
    v1, v2 = e.embed(["encrypt customer data", "encrypt customer data"])
    assert v1 == v2 and cosine(v1, v1) == pytest.approx(1.0)
    [empty] = e.embed([""])
    assert all(x == 0 for x in empty)


def test_vector_retriever_filters_server_side() -> None:
    vr = VectorRetriever(HashingEmbedder(256), InMemoryVectorStore())
    vr.index(CHUNKS)
    ids = [h.chunk.id for h in vr.retrieve("escalation note", CTX, k=10)]
    assert "d" in ids and "e" not in ids and "f" not in ids
    assert isinstance(vr, Retriever)
    with pytest.raises(ValueError):
        InMemoryVectorStore().upsert(CHUNKS[:2], [[0.0]])


def test_bm25_ranks_exact_terms_and_filters() -> None:
    idx = BM25Index()
    idx.add(CHUNKS)
    kr = KeywordRetriever(idx)
    hits = kr.retrieve("multi-factor authentication", CTX, k=3)
    assert hits[0].chunk.id == "c"
    assert all(h.chunk.id != "e" for h in kr.retrieve("escalation note", CTX, 10))
    assert idx.idf("nonexistentterm") > idx.idf("note")
    assert BM25Index().search("x", CTX, 5) == []
    assert kr.retrieve("encrypted", CTX, 5, MetadataFilter(source="none")) == []


def test_hybrid_retriever() -> None:
    vr = VectorRetriever(HashingEmbedder(256), InMemoryVectorStore())
    vr.index(CHUNKS)
    idx = BM25Index()
    idx.add(CHUNKS)
    for parallel in (False, True):
        h = HybridRetriever([vr, KeywordRetriever(idx)], parallel=parallel)
        assert h.retrieve("encrypted at rest", CTX, 3)[0].chunk.id == "b"
    with pytest.raises(ValueError):
        HybridRetriever([])


def test_lexical_reranker_prefers_coverage_and_section_refs() -> None:
    items = [
        ScoredChunk(CHUNKS[0], 1.0),
        ScoredChunk(CHUNKS[2], 0.5),
        ScoredChunk(Chunk("x", "unrelated", {"section": "314.4"}), 0.1),
    ]
    out = LexicalReranker().rerank("multi-factor authentication requirement", items, top_n=2)
    assert out[0].chunk.id == "c" and len(out) == 2
    out = LexicalReranker().rerank("what does 314.4 say", items, top_n=1)
    assert out[0].chunk.id == "x"
    assert LexicalReranker().rerank("q", [], 3) == []


def test_pipeline_configs(sample_chunks: list[Chunk]) -> None:
    s = Settings(cache_backend="none")
    rewriter = QueryRewriter(build_gateway(s), PromptRegistry(s.prompts_dir))
    p = build_pipeline(s, sample_chunks, rewriter=rewriter)
    q = "How many hours of service are needed for FMLA eligibility?"
    for name, cfg in NAMED_CONFIGS.items():
        res = p.with_config(cfg).search(q, CTX)
        assert res, name
        assert any(h.chunk.section_id == "825.110" for h in res), name
    assert len(p.search_k(q, CTX, 10)) == 10
    assert RetrievalConfig("hybrid", True, True).key == "hybrid+rerank+rewrite"
    assert p.term_weight("fmla") > 0


def test_query_rewriter_expands_abbreviations() -> None:
    s = Settings(cache_backend="none")
    rw = QueryRewriter(build_gateway(s), PromptRegistry(s.prompts_dir))
    out = rw.rewrite("Does GLBA require MFA?")
    assert out.startswith("Does GLBA require MFA?")
    assert "multi-factor authentication" in out
    assert rw.rewrite("plain question") == "plain question"
