"""Builds the retrieval pipeline from configuration so every stage is switchable for evals:
vector-only, bm25-only, hybrid, hybrid+rerank, hybrid+rerank+rewrite."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from regintel.config import Settings
from regintel.observability import metrics
from regintel.observability.tracing import span
from regintel.retrieval.base import (
    Chunk,
    Embedder,
    MetadataFilter,
    Reranker,
    Retriever,
    ScoredChunk,
    SecurityContext,
)
from regintel.retrieval.bm25 import BM25Index, KeywordRetriever
from regintel.retrieval.embeddings import HashingEmbedder
from regintel.retrieval.hybrid import HybridRetriever
from regintel.retrieval.query_rewrite import QueryRewriter
from regintel.retrieval.reranker import LexicalReranker
from regintel.retrieval.vector import InMemoryVectorStore, VectorRetriever, VectorStore


@dataclass(frozen=True)
class RetrievalConfig:
    mode: str = "hybrid"  # vector | bm25 | hybrid
    rerank: bool = True
    rewrite: bool = False
    top_k: int = 20
    top_n: int = 5
    rrf_k: int = 60

    @property
    def key(self) -> str:
        return f"{self.mode}{'+rerank' if self.rerank else ''}{'+rewrite' if self.rewrite else ''}"

    @classmethod
    def from_settings(cls, s: Settings) -> RetrievalConfig:
        return cls(
            s.retrieval_mode, s.use_rerank, s.use_query_rewrite, s.top_k, s.rerank_top_n, s.rrf_k
        )


NAMED_CONFIGS: dict[str, RetrievalConfig] = {
    "vector": RetrievalConfig("vector", rerank=False),
    "bm25": RetrievalConfig("bm25", rerank=False),
    "hybrid": RetrievalConfig("hybrid", rerank=False),
    "hybrid_rerank": RetrievalConfig("hybrid", rerank=True),
    "hybrid_rerank_rewrite": RetrievalConfig("hybrid", rerank=True, rewrite=True),
}


class RetrievalPipeline:
    def __init__(
        self,
        config: RetrievalConfig,
        vector: Retriever,
        keyword: Retriever,
        reranker: Reranker,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        self.config = config
        self.vector = vector
        self.keyword = keyword
        self.reranker = reranker
        self.rewriter = rewriter
        self._hybrid = HybridRetriever([vector, keyword], rrf_k=config.rrf_k)

    def term_weight(self, term: str) -> float:
        """Corpus IDF for confidence scoring (uniform when the keyword store has no stats)."""
        index = getattr(self.keyword, "index", None)
        return float(index.idf(term)) if isinstance(index, BM25Index) else 1.0

    def with_config(self, config: RetrievalConfig) -> RetrievalPipeline:
        return RetrievalPipeline(config, self.vector, self.keyword, self.reranker, self.rewriter)

    def _first_stage(self) -> Retriever:
        if self.config.mode == "vector":
            return self.vector
        if self.config.mode == "bm25":
            return self.keyword
        return self._hybrid

    def search(
        self, query: str, ctx: SecurityContext, filters: MetadataFilter | None = None
    ) -> list[ScoredChunk]:
        start = time.perf_counter()
        cfg = self.config
        with span("retrieval.search", mode=cfg.key):
            q = query
            if cfg.rewrite and self.rewriter is not None:
                q = self.rewriter.rewrite(query, ctx.tenant_id)
            candidates = self._first_stage().retrieve(q, ctx, cfg.top_k, filters)
            if cfg.rerank:
                results = self.reranker.rerank(q, candidates, cfg.top_n)
            else:
                results = candidates[: cfg.top_n]
        metrics.RETRIEVAL_LATENCY.labels(cfg.key).observe(time.perf_counter() - start)
        return results

    def search_k(self, query: str, ctx: SecurityContext, k: int) -> list[ScoredChunk]:
        """Search returning ``k`` results (used by evals for recall@k)."""
        return replace_top_n(self, k).search(query, ctx)


def replace_top_n(p: RetrievalPipeline, n: int) -> RetrievalPipeline:
    return p.with_config(replace(p.config, top_n=n, top_k=max(p.config.top_k, n)))


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "bge":  # pragma: no cover - needs ml extra
        from regintel.retrieval.embeddings import SentenceTransformerEmbedder

        return SentenceTransformerEmbedder(settings.embedding_model)
    return HashingEmbedder(settings.embedding_dim)


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker == "cross-encoder":  # pragma: no cover - needs ml extra
        from regintel.retrieval.reranker import CrossEncoderReranker

        return CrossEncoderReranker(settings.reranker_model)
    return LexicalReranker()


def build_pipeline(
    settings: Settings,
    chunks: list[Chunk],
    embedder: Embedder | None = None,
    rewriter: QueryRewriter | None = None,
    config: RetrievalConfig | None = None,
) -> RetrievalPipeline:
    embedder = embedder or build_embedder(settings)
    store: VectorStore
    if settings.vector_store == "qdrant":  # pragma: no cover - needs docker services
        from regintel.storage.qdrant_store import QdrantVectorStore

        qdrant = QdrantVectorStore(settings.qdrant_url, settings.qdrant_collection, embedder.dim)
        vector = VectorRetriever(embedder, qdrant)
        if qdrant.count() == 0:  # first start: seed the collection (deterministic point ids)
            vector.index(chunks)
    else:
        store = InMemoryVectorStore()
        vector = VectorRetriever(embedder, store)
        vector.index(chunks)
    keyword: Retriever
    if settings.keyword_store == "opensearch":  # pragma: no cover - needs docker services
        from regintel.storage.opensearch_store import OpenSearchKeywordStore

        keyword = OpenSearchKeywordStore(settings.opensearch_url, settings.opensearch_index)
    else:
        index = BM25Index()
        index.add(chunks)
        keyword = KeywordRetriever(index)
    return RetrievalPipeline(
        config or RetrievalConfig.from_settings(settings),
        vector,
        keyword,
        build_reranker(settings),
        rewriter,
    )


__all__ = ["NAMED_CONFIGS", "RetrievalConfig", "RetrievalPipeline", "build_pipeline", "replace"]
