"""Second-stage rerankers.

* ``CrossEncoderReranker`` - sentence-transformers cross-encoder (``ml`` extra), full mode.
* ``LexicalReranker`` - dependency-free reranker that scores each candidate on query-term
  coverage (IDF-weighted over the candidate pool), bigram/phrase matches, exact section-number
  matches and heading matches, blended with the first-stage rank. Lite mode / CI default.
"""

from __future__ import annotations

import math
import re
from typing import Any

from regintel.retrieval.base import ScoredChunk
from regintel.text import bigrams, terms

_SECTION_REF = re.compile(r"\b(\d{3,4}\.\d{1,3}[a-z]?)\b")


class LexicalReranker:
    def __init__(self, prior_weight: float = 0.35) -> None:
        self.prior_weight = prior_weight

    def rerank(self, query: str, items: list[ScoredChunk], top_n: int = 5) -> list[ScoredChunk]:
        if not items:
            return []
        q_terms = terms(query)
        q_set = set(q_terms)
        q_bigrams = bigrams(q_terms)
        q_sections = set(_SECTION_REF.findall(query))
        doc_terms = [terms(it.chunk.text) for it in items]
        n = len(items)
        df = {t: sum(1 for d in doc_terms if t in set(d)) for t in q_set}
        idf = {t: math.log(1 + (n + 1) / (df[t] + 0.5)) for t in q_set}
        total_idf = sum(idf.values()) or 1.0
        rescored: list[ScoredChunk] = []
        for rank, (item, dterms) in enumerate(zip(items, doc_terms, strict=True)):
            dset = set(dterms)
            cov = sum(idf[t] for t in q_set if t in dset) / total_idf
            bi = len(q_bigrams & bigrams(dterms)) / max(1, len(q_bigrams))
            head = (
                item.chunk.metadata.get("heading_path", "")
                + " "
                + item.chunk.metadata.get("section_title", "")
            )
            head_cov = len(q_set & set(terms(head))) / max(1, len(q_set))
            sect = 1.0 if item.chunk.section_id in q_sections else 0.0
            prior = 1.0 / (1 + rank) ** 0.5
            score = 0.45 * cov + 0.2 * bi + 0.2 * head_cov + 0.6 * sect + self.prior_weight * prior
            rescored.append(ScoredChunk(item.chunk, score))
        rescored.sort(key=lambda s: s.score, reverse=True)
        return rescored[:top_n]


class CrossEncoderReranker:  # pragma: no cover - needs ml extra + model download
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self._model: Any = CrossEncoder(model_name)

    def rerank(self, query: str, items: list[ScoredChunk], top_n: int = 5) -> list[ScoredChunk]:
        if not items:
            return []
        scores = self._model.predict([(query, it.chunk.text) for it in items])
        rescored = [ScoredChunk(it.chunk, float(s)) for it, s in zip(items, scores, strict=True)]
        rescored.sort(key=lambda s: s.score, reverse=True)
        return rescored[:top_n]
