"""OpenSearch BM25 keyword store (``stores`` extra), implementing the Retriever protocol."""

from __future__ import annotations

from typing import Any

from regintel.retrieval.base import Chunk, MetadataFilter, ScoredChunk, SecurityContext


class OpenSearchKeywordStore:
    def __init__(self, url: str, index: str) -> None:
        from opensearchpy import OpenSearch, helpers

        self._client: Any = OpenSearch(hosts=[url])
        self._helpers: Any = helpers
        self.index_name = index
        if not self._client.indices.exists(index=index):
            self._client.indices.create(
                index=index,
                body={
                    "settings": {"index": {"similarity": {"default": {"type": "BM25"}}}},
                    "mappings": {
                        "properties": {
                            "text": {"type": "text", "analyzer": "english"},
                            "section": {"type": "keyword"},
                            "tenant_id": {"type": "keyword"},
                            "allowed_groups_list": {"type": "keyword"},
                            "jurisdiction": {"type": "keyword"},
                            "act": {"type": "keyword"},
                            "source": {"type": "keyword"},
                            "metadata": {"type": "object", "enabled": False},
                        }
                    },
                },
            )

    def index(self, chunks: list[Chunk]) -> None:
        actions = [
            {
                "_index": self.index_name,
                "_id": c.id,
                "_source": {
                    "text": c.text,
                    "section": c.section_id,
                    "tenant_id": c.tenant_id,
                    "allowed_groups_list": list(c.allowed_groups),
                    "jurisdiction": c.metadata.get("jurisdiction"),
                    "act": c.metadata.get("act"),
                    "source": c.metadata.get("source"),
                    "metadata": c.metadata,
                },
            }
            for c in chunks
        ]
        self._helpers.bulk(self._client, actions, refresh=True)

    def retrieve(
        self,
        query: str,
        ctx: SecurityContext,
        k: int = 20,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        flt: list[dict[str, Any]] = [
            {"terms": {"tenant_id": ["public", ctx.tenant_id]}},
            {"terms": {"allowed_groups_list": ["*", *ctx.groups]}},
        ]
        if filters:
            for key in ("jurisdiction", "act", "source"):
                if getattr(filters, key):
                    flt.append({"term": {key: getattr(filters, key)}})
        body = {
            "size": k,
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": ["text", "section^3"]}}],
                    "filter": flt,
                }
            },
        }
        hits = self._client.search(index=self.index_name, body=body)["hits"]["hits"]
        return [
            ScoredChunk(
                Chunk(
                    h["_id"],
                    h["_source"]["text"],
                    {k2: str(v) for k2, v in h["_source"]["metadata"].items()},
                ),
                float(h["_score"]),
            )
            for h in hits
        ]
