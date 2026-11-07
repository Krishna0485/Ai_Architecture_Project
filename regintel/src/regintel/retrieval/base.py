"""Core retrieval contracts. Every component talks through these Protocols so it can be swapped
(in-memory vs Qdrant, BM25 vs OpenSearch, lexical vs cross-encoder) and tested with fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

PUBLIC_TENANT = "public"


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def section_id(self) -> str:
        return self.metadata.get("section", "")

    @property
    def tenant_id(self) -> str:
        return self.metadata.get("tenant_id", PUBLIC_TENANT)

    @property
    def allowed_groups(self) -> tuple[str, ...]:
        raw = self.metadata.get("allowed_groups", "*")
        return tuple(g.strip() for g in raw.split(",") if g.strip())


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class SecurityContext:
    """Who is asking. Built only from authenticated credentials, never from user/LLM text."""

    tenant_id: str
    groups: tuple[str, ...]
    actor: str = "anonymous"
    request_id: str = ""

    def can_see(self, chunk: Chunk) -> bool:
        if chunk.tenant_id not in (PUBLIC_TENANT, self.tenant_id):
            return False
        allowed = chunk.allowed_groups
        return "*" in allowed or bool(set(allowed) & set(self.groups))


@dataclass(frozen=True)
class MetadataFilter:
    """Optional user-facing narrowing filters (applied *in addition to* security filters)."""

    jurisdiction: str | None = None
    act: str | None = None
    source: str | None = None

    def matches(self, chunk: Chunk) -> bool:
        md = chunk.metadata
        return (
            (self.jurisdiction is None or md.get("jurisdiction") == self.jurisdiction)
            and (self.act is None or md.get("act") == self.act)
            and (self.source is None or md.get("source") == self.source)
        )


@runtime_checkable
class Retriever(Protocol):
    def retrieve(
        self,
        query: str,
        ctx: SecurityContext,
        k: int = 20,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(self, query: str, items: list[ScoredChunk], top_n: int = 5) -> list[ScoredChunk]: ...


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]: ...


def reciprocal_rank_fusion(lists: list[list[ScoredChunk]], k: int = 60) -> list[ScoredChunk]:
    """Fuse ranked lists by RRF: score(d) = sum_i 1 / (k + rank_i(d)). Rank-based, so it needs
    no score calibration between BM25 and cosine similarity."""
    scores: dict[str, float] = {}
    by_id: dict[str, Chunk] = {}
    for ranked in lists:
        for pos, item in enumerate(ranked):
            by_id[item.chunk.id] = item.chunk
            scores[item.chunk.id] = scores.get(item.chunk.id, 0.0) + 1.0 / (k + pos + 1)
    ordered = sorted(scores, key=scores.__getitem__, reverse=True)
    return [ScoredChunk(by_id[i], scores[i]) for i in ordered]
