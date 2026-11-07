"""Small, dependency-free text utilities shared by chunking, retrieval and evaluation."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable

_TOKEN_RE = re.compile(r"\d+(?:\.\d+)+|\w+|[^\w\s]")
_WORD_RE = re.compile(r"\d+(?:\.\d+)+[a-z]?|[a-z0-9]+")
_SENT_RE = re.compile(r"(?<=[.;:!?])\s+(?=[(\"A-Z0-9§])")

STOPWORDS: frozenset[str] = frozenset(
    """a an and are as at be been but by can could do does for from had has have how i if in
    into is it its may might must not of on or other our shall should so such than that the their
    them then there these they this those to under upon was we were what when where whether which
    who whom why will with within without would you your any all also each per many much""".split()
)


def count_tokens(text: str) -> int:
    """Approximate LLM token count (word pieces + punctuation). Good enough for budgeting."""
    return int(len(_TOKEN_RE.findall(text)) * 1.15)


def normalize_term(term: str) -> str:
    """Very light stemmer: lowercase and strip common English suffixes."""
    t = term.lower()
    if len(t) <= 3 or t[0].isdigit():
        return t
    if t.endswith("ees"):  # employees -> employee
        t = t[:-1]
    else:
        for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
            if t.endswith(suffix) and len(t) - len(suffix) >= 3:
                t = t[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
    # Porter-style final "e" removal keeps stems consistent: entitle(ment) / entitl(ed).
    return t[:-1] if t.endswith("e") and len(t) > 4 else t


def terms(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Tokenise into normalised terms. Section numbers like ``314.4`` are kept intact."""
    out: list[str] = []
    for raw in _WORD_RE.findall(text.lower()):
        if not keep_stopwords and raw in STOPWORDS:
            continue
        out.append(normalize_term(raw))
    return out


def content_terms(text: str) -> set[str]:
    return set(terms(text))


def sentences(text: str) -> list[str]:
    """Split text into sentences (regulation-friendly: also splits on ``;`` boundaries)."""
    parts = [p.strip() for p in _SENT_RE.split(text.replace("\n", " "))]
    return [p for p in parts if p]


def coverage(query: str, text: str) -> float:
    """Fraction of the query's content terms that appear in ``text`` (0..1)."""
    q = content_terms(query)
    if not q:
        return 0.0
    return len(q & content_terms(text)) / len(q)


def token_f1(prediction: str, reference: str) -> float:
    """SQuAD-style token F1 between two strings on content terms."""
    p, r = terms(prediction), terms(reference)
    if not p or not r:
        return 0.0
    common: dict[str, int] = {}
    rc: dict[str, int] = {}
    for t in r:
        rc[t] = rc.get(t, 0) + 1
    for t in p:
        if rc.get(t, 0) > 0:
            common[t] = common.get(t, 0) + 1
            rc[t] -= 1
    n = sum(common.values())
    if n == 0:
        return 0.0
    precision, recall = n / len(p), n / len(r)
    return 2 * precision * recall / (precision + recall)


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len].rstrip("_") or "item"


def bigrams(items: Iterable[str]) -> set[tuple[str, str]]:
    seq = list(items)
    return set(itertools.pairwise(seq))
