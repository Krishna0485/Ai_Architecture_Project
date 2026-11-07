"""LLM-as-judge with a fixed rubric, plus calibration against human labels.

The judge is any callable ``(prompt) -> str`` so it works with every provider (OpenAI-compatible
client, LiteLLM, Anthropic SDK, a local model). Scores are parsed from JSON ``{"score": 1-5}``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

RUBRIC = """You are an evaluation judge. Grade the candidate answer against the reference answer
for factual correctness and completeness on a 1-5 scale:
5 = fully correct and complete; 4 = correct, minor omission; 3 = partially correct;
2 = mostly incorrect or unsupported; 1 = wrong or irrelevant. Ignore style.
Return JSON only: {{"score": <1-5>, "reason": "<one sentence>"}}

Question: {question}
Reference answer: {reference}
Candidate answer: {answer}
"""


def build_prompt(question: str, answer: str, reference: str) -> str:
    return RUBRIC.format(question=question, answer=answer, reference=reference)


def parse_score(text: str) -> int | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        score = int(json.loads(match.group())["score"])
    except (ValueError, KeyError, TypeError):
        return None
    return score if 1 <= score <= 5 else None


def judge(llm: Callable[[str], str], question: str, answer: str, reference: str) -> int | None:
    return parse_score(llm(build_prompt(question, answer, reference)))


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("need two equal-length sequences with >= 2 items")
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else 0.0


@dataclass(frozen=True)
class Calibration:
    n: int
    spearman: float
    exact_agreement: float
    within_one: float
    mean_bias: float  # judge - human; positive = judge is lenient


def calibrate(human: Sequence[int], judged: Sequence[int]) -> Calibration:
    """Agreement between human labels and judge scores on the same items."""
    if len(human) != len(judged) or not human:
        raise ValueError("human and judged must be non-empty and equal length")
    n = len(human)
    return Calibration(
        n=n,
        spearman=round(spearman(human, judged), 4) if n >= 2 else 0.0,
        exact_agreement=round(sum(h == j for h, j in zip(human, judged, strict=True)) / n, 4),
        within_one=round(sum(abs(h - j) <= 1 for h, j in zip(human, judged, strict=True)) / n, 4),
        mean_bias=round(sum(j - h for h, j in zip(human, judged, strict=True)) / n, 4),
    )
