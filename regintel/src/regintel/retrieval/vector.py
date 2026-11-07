"""Dense vector retrieval. Security filters are applied inside the store (server-side), before
ranking, so a tenant can never receive another tenant's chunk even transiently."""

from __future__ import annotations

from typing import Protocol

from regintel.retrieval.base import (
    Chunk,
    Embedder,
    MetadataFilter,
    ScoredChunk,
    SecurityContext,
)
from regintel.retrieval.embeddings import cosine


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def search(
        self,
        vector: list[float],
        ctx: SecurityContext,
        k: int,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[Chunk, list[float]]] = {}

    def __len__(self) -> int:
        return len(self._rows)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        for c, v in zip(chunks, vectors, strict=True):
            self._rows[c.id] = (c, v)

    def search(
        self,
        vector: list[float],
        ctx: SecurityContext,
        k: int,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(c, cosine(vector, v))
            for c, v in self._rows.values()
            if ctx.can_see(c) and (filters is None or filters.matches(c))
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]


class VectorRetriever:
    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self.embedder = embedder
        self.store = store

    def index(self, chunks: list[Chunk]) -> None:
        self.store.upsert(chunks, self.embedder.embed([c.text for c in chunks]))

    def retrieve(
        self,
        query: str,
        ctx: SecurityContext,
        k: int = 20,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        [qv] = self.embedder.embed([query], is_query=True)
        return self.store.search(qv, ctx, k, filters)
