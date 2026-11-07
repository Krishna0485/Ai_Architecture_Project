"""Tests against real docker-compose services (make up). Skipped when they are not reachable."""

from __future__ import annotations

import socket

import pytest

from regintel.retrieval.base import SecurityContext

pytestmark = pytest.mark.docker


def _up(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _up("localhost", 6333), reason="qdrant not running (make up)")
def test_qdrant_store_enforces_tenant_filter(sample_chunks: list) -> None:  # type: ignore[type-arg]
    qdrant = pytest.importorskip("qdrant_client")
    assert qdrant
    from regintel.retrieval.embeddings import HashingEmbedder
    from regintel.storage.qdrant_store import QdrantVectorStore

    emb = HashingEmbedder(256)
    store = QdrantVectorStore("http://localhost:6333", "regintel_test", 256)
    store.upsert(sample_chunks, emb.embed([c.text for c in sample_chunks]))
    ctx = SecurityContext("globex", ("compliance",))
    [qv] = emb.embed(["ACME-CANARY-7731 escalation"], is_query=True)
    hits = store.search(qv, ctx, 20)
    assert hits and all(h.chunk.tenant_id in ("public", "globex") for h in hits)


@pytest.mark.skipif(not _up("localhost", 9200), reason="opensearch not running (make up)")
def test_opensearch_keyword_store(sample_chunks: list) -> None:  # type: ignore[type-arg]
    pytest.importorskip("opensearchpy")
    from regintel.storage.opensearch_store import OpenSearchKeywordStore

    store = OpenSearchKeywordStore("http://localhost:9200", "regintel_test")
    store.index(sample_chunks)
    hits = store.retrieve("825.110 hours of service", SecurityContext("acme", ("compliance",)), 5)
    assert hits and hits[0].chunk.section_id == "825.110"
