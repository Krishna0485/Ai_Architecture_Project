"""Okapi BM25 keyword retrieval (pure Python). Exact legal terms and section numbers such as
``825.110`` are preserved as single tokens, which is where BM25 beats dense vectors."""

from __future__ import annotations

import math
from collections import Counter

from regintel.retrieval.base import Chunk, MetadataFilter, ScoredChunk, SecurityContext
from regintel.text import terms


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[Chunk] = []
        self._tfs: list[Counter[str]] = []
        self._lens: list[int] = []
        self._df: Counter[str] = Counter()
        self._postings: dict[str, list[int]] = {}

    def __len__(self) -> int:
        return len(self._docs)

    def add(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            tf = Counter(terms(c.text))
            idx = len(self._docs)
            self._docs.append(c)
            self._tfs.append(tf)
            self._lens.append(sum(tf.values()))
            for t in tf:
                self._df[t] += 1
                self._postings.setdefault(t, []).append(idx)

    def idf(self, term: str) -> float:
        """BM25 IDF (terms absent from the corpus get the maximum value)."""
        n = len(self._docs)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        ctx: SecurityContext,
        k: int,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        if not self._docs:
            return []
        avgdl = sum(self._lens) / len(self._lens)
        scores: dict[int, float] = {}
        for t in set(terms(query)):
            postings = self._postings.get(t)
            if not postings:
                continue
            idf = self.idf(t)
            for i in postings:
                tf = self._tfs[i][t]
                denom = tf + self.k1 * (1 - self.b + self.b * self._lens[i] / avgdl)
                scores[i] = scores.get(i, 0.0) + idf * tf * (self.k1 + 1) / denom
        ranked = [
            ScoredChunk(self._docs[i], s)
            for i, s in scores.items()
            if ctx.can_see(self._docs[i]) and (filters is None or filters.matches(self._docs[i]))
        ]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked[:k]


class KeywordRetriever:
    def __init__(self, index: BM25Index) -> None:
        self.index = index

    def retrieve(
        self,
        query: str,
        ctx: SecurityContext,
        k: int = 20,
        filters: MetadataFilter | None = None,
    ) -> list[ScoredChunk]:
        return self.index.search(query, ctx, k, filters)
