"""PII detection and redaction.

``RegexPIIRedactor`` is built in (emails, phones, US SSN, payment cards with Luhn check, IBAN,
IPv4, Indian PAN/Aadhaar and the synthetic employee/customer IDs used in data/synthetic).
``PresidioPIIRedactor`` adds NER (names, locations) with the same custom recognisers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PIIEntity:
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class RedactionResult:
    text: str
    entities: list[PIIEntity] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.entities)


class PIIRedactor(Protocol):
    def redact(self, text: str) -> RedactionResult: ...


def _luhn_ok(digits: str) -> bool:
    nums = [int(d) for d in digits if d.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("US_SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    (
        "IP_ADDRESS",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    ),
    ("IN_PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IN_AADHAAR", re.compile(r"(?<!\d)(?<!\d[ -])[2-9]\d{3} \d{4} \d{4}(?![ -]?\d)")),
    # Custom recognisers for identifiers in the synthetic corpus.
    ("EMPLOYEE_ID", re.compile(r"\bEMP-\d{6}\b")),
    ("CUSTOMER_ID", re.compile(r"\bCUST-\d{8}\b")),
]


def _merge(entities: list[PIIEntity]) -> list[PIIEntity]:
    out: list[PIIEntity] = []
    for e in sorted(entities, key=lambda e: (e.start, -(e.end - e.start))):
        if out and e.start < out[-1].end:
            continue
        out.append(e)
    return out


def _apply(text: str, entities: list[PIIEntity]) -> str:
    parts: list[str] = []
    last = 0
    for e in entities:
        parts.append(text[last : e.start])
        parts.append(f"<{e.kind}>")
        last = e.end
    parts.append(text[last:])
    return "".join(parts)


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(digits: str) -> bool:
    """Aadhaar numbers carry a Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed([d for d in digits if d.isdigit()])):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


class RegexPIIRedactor:
    def detect(self, text: str) -> list[PIIEntity]:
        found: list[PIIEntity] = []
        for kind, pattern in PATTERNS:
            for m in pattern.finditer(text):
                if kind == "CREDIT_CARD" and not _luhn_ok(m.group()):
                    continue
                if kind == "IN_AADHAAR" and not _verhoeff_ok(m.group()):
                    continue
                if kind == "IP_ADDRESS" and re.fullmatch(r"\d{1,3}\.\d{1,3}", m.group()):
                    continue
                found.append(PIIEntity(kind, m.start(), m.end()))
        return _merge(found)

    def redact(self, text: str) -> RedactionResult:
        entities = self.detect(text)
        return RedactionResult(_apply(text, entities), entities)


class PresidioPIIRedactor:  # pragma: no cover - needs guardrails extra + spaCy model
    ENTITIES = (
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "IBAN_CODE",
        "IP_ADDRESS",
        "LOCATION",
        "EMPLOYEE_ID",
        "CUSTOMER_ID",
    )

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer

        self._engine: Any = AnalyzerEngine()
        for name, regex in (("EMPLOYEE_ID", r"\bEMP-\d{6}\b"), ("CUSTOMER_ID", r"\bCUST-\d{8}\b")):
            self._engine.registry.add_recognizer(
                PatternRecognizer(supported_entity=name, patterns=[Pattern(name, regex, 0.9)])
            )
        self._fallback = RegexPIIRedactor()

    def redact(self, text: str) -> RedactionResult:
        results = self._engine.analyze(text=text, language="en", entities=self.ENTITIES)
        entities = [PIIEntity(r.entity_type, r.start, r.end) for r in results if r.score >= 0.5]
        entities = _merge(entities + self._fallback.detect(text))
        return RedactionResult(_apply(text, entities), entities)


def build_redactor(backend: str) -> PIIRedactor:
    if backend == "presidio":  # pragma: no cover
        return PresidioPIIRedactor()
    return RegexPIIRedactor()
