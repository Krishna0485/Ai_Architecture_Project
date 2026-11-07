from __future__ import annotations

import time

import pytest

from regintel.cache.base import InMemoryCache
from regintel.cache.semantic import SemanticCache
from regintel.retrieval.embeddings import HashingEmbedder


def test_in_memory_lru_and_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    c = InMemoryCache(max_items=2, ttl_s=10)
    c.set("a", "1")
    c.set("b", "2")
    assert c.get("a") == "1"  # a becomes most recent
    c.set("c", "3")
    assert c.get("b") is None and c.get("a") == "1"
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 100)
    assert c.get("a") is None
    c.clear()


def test_in_memory_lists() -> None:
    c = InMemoryCache(max_items=2)
    for i in range(3):
        c.append("ns", str(i))
    assert c.items("ns") == ["1", "2"] and c.items("other") == []


def test_semantic_cache_namespaces_and_threshold() -> None:
    sc = SemanticCache(HashingEmbedder(512), InMemoryCache(), threshold=0.9)
    ns = SemanticCache.namespace("acme", "answer.v1", "hybrid")
    sc.store(ns, "How many weeks of FMLA leave?", {"answer": "12"})
    hit = sc.lookup(ns, "How many weeks of FMLA leave?")
    assert hit is not None and hit.payload == {"answer": "12"} and hit.similarity > 0.99
    assert sc.lookup(ns, "What is encryption at rest?") is None
    assert (
        sc.lookup(
            SemanticCache.namespace("globex", "answer.v1", "hybrid"),
            "How many weeks of FMLA leave?",
        )
        is None
    )  # tenant isolation
    assert sc.hit_rate == pytest.approx(1 / 3)
