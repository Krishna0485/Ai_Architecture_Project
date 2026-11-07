"""Hybrid retrieval: run several retrievers and fuse with Reciprocal Rank Fusion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from regintel.retrieval.base import (
    MetadataFilter,
    Retriever,
    ScoredChunk,
    SecurityContext,
    reciprocal_rank_fusion,
)


class HybridRetriever:
    def __init__(
        self, retrievers: list[Retriever], rrf_k: int = 60, parallel: bool = False
    ) -> None:
        if not retrievers:
            raise ValueError("at least one retriever required")
        self.retrievers = retrievers
        self.rrf_k = rrf_k
        self.parallel = parallel

    def retrieve(
        self,
        query: str,
        ctx: SecurityContext,
        k: int = 20,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        if self.parallel and len(self.retrievers) > 1:
            with ThreadPoolExecutor(max_workers=len(self.retrievers)) as pool:
                lists = list(
                    pool.map(lambda r: r.retrieve(query, ctx, k, filters), self.retrievers)
                )
        else:
            lists = [r.retrieve(query, ctx, k, filters) for r in self.retrievers]
        return reciprocal_rank_fusion(lists, k=self.rrf_k)[:k]
