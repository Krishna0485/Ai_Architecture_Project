"""Prompt-injection scanning for untrusted text (uploads and retrieved chunks).

Heuristic signals are scored and combined; an optional classifier can be plugged in. Scanning is
defence-in-depth only - the primary control is architectural (quarantine pattern: the model that
reads untrusted text has no tools and can only emit schema-validated facts).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import dataclass, field

_SIGNALS: list[tuple[str, float, re.Pattern[str]]] = [
    (
        "override_instructions",
        0.6,
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|all|earlier|"
            r"system)\b[^.\n]{0,20}\b(instructions?|prompts?|rules?|context)",
            re.I,
        ),
    ),
    (
        "role_hijack",
        0.45,
        re.compile(
            r"\b(you are now|act as|pretend to be|from now on you|new instructions?:)", re.I
        ),
    ),
    (
        "system_prompt_probe",
        0.5,
        re.compile(
            r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,30}"
            r"\b(system prompt|instructions|hidden)",
            re.I,
        ),
    ),
    (
        "tool_invocation",
        0.5,
        re.compile(
            r"\b(call|invoke|execute|run|use)\b[^.\n]{0,20}\b(tool|function|command|shell|api)\b"
            r"|<\s*tool_call|\"function_call\"",
            re.I,
        ),
    ),
    (
        "verdict_manipulation",
        0.55,
        re.compile(
            r"\b(mark|report|classify|treat|consider)\b[^.\n]{0,40}\b(all|every|this)\b[^.\n]{0,30}"
            r"\b(compliant|approved|passed|no (?:gaps|findings|issues))",
            re.I,
        ),
    ),
    (
        "exfiltration",
        0.5,
        re.compile(
            r"\b(send|post|upload|exfiltrate|forward)\b[^.\n]{0,40}\b(https?://|webhook|email|"
            r"credentials?|api[ _-]?keys?|tokens?)",
            re.I,
        ),
    ),
    (
        "delimiter_spoof",
        0.4,
        re.compile(
            r"</?\s*(untrusted|system|assistant|instructions?)\s*>|\[/?INST\]|<\|im_(start|end)\|>",
            re.I,
        ),
    ),
    (
        "addressed_to_ai",
        0.3,
        re.compile(
            r"\b(AI|assistant|language model|LLM|chatbot)\b\s*[,:]?\s*(please\s+)?"
            r"(must|should|ignore|do|note)\b",
            re.I,
        ),
    ),
]
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
_B64 = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}")


@dataclass(frozen=True)
class InjectionResult:
    score: float
    signals: list[str] = field(default_factory=list)
    threshold: float = 0.5

    @property
    def is_suspicious(self) -> bool:
        return self.score >= self.threshold


class InjectionScanner:
    def __init__(
        self,
        threshold: float = 0.5,
        classifier: Callable[[str], float] | None = None,
    ) -> None:
        self.threshold = threshold
        self.classifier = classifier

    def _decoded_payloads(self, text: str) -> list[str]:
        out: list[str] = []
        for m in _B64.finditer(text):
            try:
                decoded = base64.b64decode(m.group(), validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
            if decoded.isprintable():
                out.append(decoded)
        return out

    def scan(self, text: str) -> InjectionResult:
        signals: list[str] = []
        score = 0.0
        if _ZERO_WIDTH.search(text):
            signals.append("hidden_unicode")
            score += 0.3
        for payload in [text, *self._decoded_payloads(text)]:
            for name, weight, pattern in _SIGNALS:
                if name not in signals and pattern.search(payload):
                    signals.append(name)
                    score += weight
        if self.classifier is not None:  # pragma: no cover - optional model
            score = max(score, self.classifier(text))
        return InjectionResult(min(1.0, score), signals, self.threshold)

    def split_suspicious(self, text: str) -> tuple[str, list[str]]:
        """Return (clean_text, quarantined_lines): drop individual suspicious lines."""
        clean, quarantined = [], []
        for line in text.splitlines():
            if line.strip() and self.scan(line).is_suspicious:
                quarantined.append(line)
            else:
                clean.append(line)
        return "\n".join(clean), quarantined
