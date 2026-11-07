"""Retrieval metrics over *section-level* relevance.

A retrieved chunk is relevant when its ``source:section`` is in the item's relevant sections.
Section-level labels survive re-chunking, so the golden set does not need to change when the
chunker does (see docs/evaluation.md).
"""

from __future__ import annotations

from collections.abc import Sequence


def hit_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """1.0 if any of the top-k items is relevant."""
    return 1.0 if any(r in relevant for r in ranked[:k]) else 0.0


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Fraction of distinct relevant items found in the top-k."""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str], k: int | None = None) -> float:
    """1/rank of the first relevant item (0 if none within k)."""
    for i, r in enumerate(ranked[:k] if k else ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def average_precision(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Rank-aware precision (as in RAGAS context precision): mean of precision@i at each
    relevant position i <= k, normalised by the number of relevant positions retrieved."""
    hits, total = 0, 0.0
    for i, r in enumerate(ranked[:k], start=1):
        if r in relevant:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
