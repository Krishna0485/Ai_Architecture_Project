"""Context compression: fit retrieved chunks into a token budget.

1. Drop near-duplicate chunks (same section, high overlap).
2. Keep whole chunks in rank order while they fit.
3. For the first chunk that does not fit, keep only its most query-relevant sentences.
"""

from __future__ import annotations

from regintel.retrieval.base import Chunk, ScoredChunk
from regintel.text import content_terms, count_tokens, coverage, sentences


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def compress_context(
    query: str, items: list[ScoredChunk], budget_tokens: int, dedupe_threshold: float = 0.85
) -> list[ScoredChunk]:
    kept: list[ScoredChunk] = []
    kept_terms: list[set[str]] = []
    used = 0
    for item in items:
        t = content_terms(item.chunk.text)
        if any(_jaccard(t, k) >= dedupe_threshold for k in kept_terms):
            continue
        n = count_tokens(item.chunk.text)
        if used + n <= budget_tokens:
            kept.append(item)
            kept_terms.append(t)
            used += n
            continue
        remaining = budget_tokens - used
        if remaining < 60:
            break
        header, _, body = item.chunk.text.partition("\n")
        ranked = sorted(sentences(body or header), key=lambda s: coverage(query, s), reverse=True)
        picked: list[str] = []
        size = count_tokens(header)
        for s in ranked:
            if coverage(query, s) == 0:
                break
            if size + count_tokens(s) > remaining:
                continue
            picked.append(s)
            size += count_tokens(s)
        if picked:
            order = {s: i for i, s in enumerate(sentences(body or header))}
            picked.sort(key=lambda s: order.get(s, 0))
            text = f"{header}\n{' '.join(picked)} [compressed]"
            kept.append(ScoredChunk(Chunk(item.chunk.id, text, item.chunk.metadata), item.score))
            used += size
        break
    return kept
