"""Embedders behind the ``Embedder`` protocol.

* ``HashingEmbedder`` - dependency-free, deterministic feature hashing of word unigrams and
  character trigrams. Used in lite mode / CI so evaluation is hermetic and reproducible.
* ``SentenceTransformerEmbedder`` - BGE dense embeddings (``ml`` extra), used in full mode.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from regintel.text import terms


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


class HashingEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % self.dim
        sign = 1.0 if h[4] & 1 else -1.0
        return idx, sign

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = terms(text)
        counts: dict[str, int] = {}
        for w in words:
            counts["w:" + w] = counts.get("w:" + w, 0) + 1
            padded = f"#{w}#"
            for i in range(len(padded) - 2):
                tri = "c:" + padded[i : i + 3]
                counts[tri] = counts.get(tri, 0) + 1
        for feature, c in counts.items():
            idx, sign = self._bucket(feature)
            weight = (1.0 + math.log(c)) * (2.0 if feature.startswith("w:") else 0.5)
            vec[idx] += sign * weight
        return _l2_normalize(vec)

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class SentenceTransformerEmbedder:  # pragma: no cover - needs the ml extra + model download
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model: Any = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        inputs = [self.QUERY_PREFIX + t for t in texts] if is_query else texts
        vectors = self._model.encode(inputs, normalize_embeddings=True, batch_size=32)
        return [list(map(float, v)) for v in vectors]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for already-normalised vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))
