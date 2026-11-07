"""Qdrant vector store (``stores`` extra). Tenant and group filters are pushed into the Qdrant
query as payload filters, so isolation is enforced server-side."""

from __future__ import annotations

import uuid
from typing import Any

from regintel.retrieval.base import Chunk, MetadataFilter, ScoredChunk, SecurityContext


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, dim: int) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qm

        self._qm: Any = qm
        self._client: Any = QdrantClient(url=url) if url != ":memory:" else QdrantClient(":memory:")
        self.collection = collection
        if not self._client.collection_exists(collection):
            self._client.create_collection(
                collection,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
                # Scalar int8 quantisation: ~4x less memory, negligible recall loss at this scale.
                quantization_config=qm.ScalarQuantization(
                    scalar=qm.ScalarQuantizationConfig(type=qm.ScalarType.INT8, always_ram=True)
                ),
            )
            for field in ("tenant_id", "allowed_groups_list", "jurisdiction", "act", "source"):
                self._client.create_payload_index(collection, field, qm.PayloadSchemaType.KEYWORD)

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    def count(self) -> int:
        return int(self._client.count(self.collection, exact=True).count)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        qm = self._qm
        points = [
            qm.PointStruct(
                id=self._point_id(c.id),
                vector=v,
                payload={
                    **c.metadata,
                    "chunk_id": c.id,
                    "text": c.text,
                    "allowed_groups_list": list(c.allowed_groups),
                },
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        for i in range(0, len(points), 256):
            self._client.upsert(self.collection, points=points[i : i + 256])

    def _filter(self, ctx: SecurityContext, filters: MetadataFilter | None) -> Any:
        qm = self._qm
        must = [
            qm.FieldCondition(key="tenant_id", match=qm.MatchAny(any=["public", ctx.tenant_id])),
            qm.FieldCondition(key="allowed_groups_list", match=qm.MatchAny(any=["*", *ctx.groups])),
        ]
        if filters:
            for key in ("jurisdiction", "act", "source"):
                value = getattr(filters, key)
                if value:
                    must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
        return qm.Filter(must=must)

    def search(
        self,
        vector: list[float],
        ctx: SecurityContext,
        k: int,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        res = self._client.query_points(
            self.collection,
            query=vector,
            limit=k,
            query_filter=self._filter(ctx, filters),
            with_payload=True,
        )
        out: list[ScoredChunk] = []
        for p in res.points:
            payload = dict(p.payload or {})
            text = str(payload.pop("text", ""))
            chunk_id = str(payload.pop("chunk_id"))
            payload.pop("allowed_groups_list", None)
            out.append(
                ScoredChunk(
                    Chunk(chunk_id, text, {k2: str(v) for k2, v in payload.items()}), float(p.score)
                )
            )
        return out
