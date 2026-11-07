"""Semantic cache for shared-knowledge questions.

Namespaced by tenant + prompt version + retrieval config, so a prompt change or a different
tenant never sees a stale/foreign answer. A hit requires cosine similarity >= threshold.
At scale the linear scan would be replaced by a Redis vector index (RediSearch HNSW).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from regintel.cache.base import ListBackend
from regintel.observability import metrics
from regintel.retrieval.base import Embedder
from regintel.retrieval.embeddings import cosine


@dataclass(frozen=True)
class CacheHit:
    payload: dict[str, Any]
    similarity: float
    matched_query: str


class SemanticCache:
    def __init__(self, embedder: Embedder, backend: ListBackend, threshold: float = 0.93) -> None:
        self.embedder = embedder
        self.backend = backend
        self.threshold = threshold
        self.hits = 0
        self.misses = 0

    @staticmethod
    def namespace(tenant_id: str, prompt_id: str, config_key: str) -> str:
        return f"{tenant_id}|{prompt_id}|{config_key}"

    def lookup(self, namespace: str, query: str) -> CacheHit | None:
        [qv] = self.embedder.embed([query], is_query=True)
        best: CacheHit | None = None
        for raw in self.backend.items(namespace):
            row = json.loads(raw)
            sim = cosine(qv, row["v"])
            if sim >= self.threshold and (best is None or sim > best.similarity):
                best = CacheHit(row["p"], sim, row["q"])
        if best is None:
            self.misses += 1
            metrics.CACHE_EVENTS.labels("semantic", "miss").inc()
        else:
            self.hits += 1
            metrics.CACHE_EVENTS.labels("semantic", "hit").inc()
        return best

    def store(self, namespace: str, query: str, payload: dict[str, Any]) -> None:
        [qv] = self.embedder.embed([query], is_query=True)
        self.backend.append(namespace, json.dumps({"q": query, "v": qv, "p": payload}))

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
