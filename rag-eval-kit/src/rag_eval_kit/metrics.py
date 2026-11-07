"""Metric definitions (see docs/metrics.md). Pure functions, stdlib only."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

_WORD = re.compile(r"\d+(?:\.\d+)+|[a-z0-9]+")
_SENT = re.compile(r"(?<=[.;!?])\s+")
_CITE = re.compile(r"\[\d{1,3}\]")
STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from has have how i if in into is it its "
    "may must not of on or our shall should so such than that the their them then there these "
    "they this those to under was we were what when where which who why will with would you your "
    "any all also each per many much".split()
)


def _stem(t: str) -> str:
    if len(t) <= 3 or t[0].isdigit():
        return t
    if t.endswith("ees"):  # employees -> employee (then -> employe, same as the singular)
        t = t[:-1]
    else:
        for suf in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)] + ("y" if suf == "ies" else "")
                break
    return t[:-1] if t.endswith("e") and len(t) > 4 else t


def terms(text: str) -> list[str]:
    """Lower-cased, stop-word-filtered, lightly stemmed tokens."""
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ----------------------------------------------------------------------------- retrieval
def hit_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """1.0 if any of the top-k ids is relevant, else 0.0."""
    return 1.0 if any(r in relevant for r in ranked[:k]) else 0.0


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Distinct relevant ids found in the top-k, divided by the number of relevant ids."""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    top = ranked[:k]
    return sum(r in relevant for r in top) / len(top) if top else 0.0


def reciprocal_rank(ranked: Sequence[str], relevant: set[str], k: int | None = None) -> float:
    """1 / rank of the first relevant id (0 if none within k)."""
    for i, r in enumerate(ranked[:k] if k else ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def average_precision(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Mean of precision@i over the relevant positions i <= k (RAGAS-style context precision)."""
    hits, total = 0, 0.0
    for i, r in enumerate(ranked[:k], start=1):
        if r in relevant:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG@k (duplicates count once)."""
    seen: set[str] = set()
    dcg = 0.0
    for i, r in enumerate(ranked[:k], start=1):
        if r in relevant and r not in seen:
            dcg += 1 / math.log2(i + 1)
            seen.add(r)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


# ---------------------------------------------------------------------------- generation
def faithfulness(answer: str, contexts: Sequence[str], support_threshold: float = 0.6) -> float:
    """Lexical proxy: share of answer sentences whose content terms are >= threshold covered by
    the contexts. Deterministic and free; use RAGAS for an LLM-judged score."""
    if not contexts:
        return 0.0
    support = set().union(*(set(terms(c)) for c in contexts))
    sents = [s for s in _SENT.split(_CITE.sub("", answer)) if terms(s)]
    if not sents:
        return 0.0
    ok = sum(
        1 for s in sents if len(set(terms(s)) & support) / len(set(terms(s))) >= support_threshold
    )
    return ok / len(sents)


def answer_relevancy(question: str, answer: str) -> float:
    """Lexical proxy: share of the question's content terms addressed in the answer."""
    q = set(terms(question))
    return len(q & set(terms(answer))) / len(q) if q else 0.0


def answer_f1(answer: str, reference: str) -> float:
    """SQuAD-style token F1 between answer and reference."""
    p, r = terms(_CITE.sub("", answer)), terms(reference)
    if not p or not r:
        return 0.0
    counts: dict[str, int] = {}
    for t in r:
        counts[t] = counts.get(t, 0) + 1
    common = 0
    for t in p:
        if counts.get(t, 0) > 0:
            common += 1
            counts[t] -= 1
    if not common:
        return 0.0
    prec, rec = common / len(p), common / len(r)
    return 2 * prec * rec / (prec + rec)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in [0, 100])."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, math.ceil(q / 100 * len(s)) - 1))
    return s[idx]
