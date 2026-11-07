"""Generation metrics.

These are deterministic *lexical proxies* for the RAGAS metrics of the same name, so the CI gate is
hermetic. ``ragas_runner.py`` computes the LLM-judged RAGAS versions when a judge model is
configured; reports always label which variant produced a number.
"""

from __future__ import annotations

import re

from regintel.text import content_terms, sentences, terms, token_f1

_CITE = re.compile(r"\[\d{1,2}\]")


def faithfulness(answer: str, cited_texts: list[str], support_threshold: float = 0.6) -> float:
    """Fraction of answer sentences whose content terms are >= threshold covered by the text of
    the passages the answer cites. 0 when nothing is cited."""
    if not cited_texts:
        return 0.0
    support = set().union(*(content_terms(t) for t in cited_texts))
    sents = [s for s in sentences(_CITE.sub("", answer)) if terms(s)]
    if not sents:
        return 0.0
    ok = 0
    for s in sents:
        st = content_terms(s)
        if st and len(st & support) / len(st) >= support_threshold:
            ok += 1
    return ok / len(sents)


def answer_relevancy(question: str, answer: str) -> float:
    """Share of the question's content terms addressed in the answer (proxy)."""
    q = content_terms(question)
    if not q:
        return 0.0
    return len(q & content_terms(answer)) / len(q)


def answer_f1(answer: str, reference: str) -> float:
    return token_f1(_CITE.sub("", answer), reference)
