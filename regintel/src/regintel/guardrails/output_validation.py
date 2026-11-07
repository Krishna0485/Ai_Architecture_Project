"""Output validation for model text: schema, citations, PII, links, markup."""

from __future__ import annotations

import html
import json
import re
from typing import TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from regintel.guardrails.pii import PIIRedactor

T = TypeVar("T", bound=BaseModel)

_URL = re.compile(r"https?://[^\s)\]>\"']+")
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class OutputValidationError(ValueError):
    pass


def parse_structured[T: BaseModel](text: str, model: type[T]) -> T:
    """Parse model output into a Pydantic model; tolerate code fences / prose around JSON."""
    candidate = text.strip()
    if not candidate.startswith("{"):
        m = _JSON_BLOCK.search(candidate)
        if not m:
            raise OutputValidationError(f"no JSON object in output for {model.__name__}")
        candidate = m.group()
    try:
        return model.model_validate(json.loads(candidate))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise OutputValidationError(f"invalid {model.__name__}: {exc}") from exc


def strip_disallowed_links(text: str, allowed_domains: list[str]) -> str:
    allowed = {d.lower() for d in allowed_domains}

    def repl(m: re.Match[str]) -> str:
        host = (urlparse(m.group()).hostname or "").lower()
        return m.group() if host in allowed else "[link removed]"

    return _URL.sub(repl, text)


def sanitize_text(text: str, redactor: PIIRedactor, allowed_domains: list[str]) -> str:
    """Redact PII, drop non-allow-listed links and HTML-escape so output is inert when rendered.
    (Model output is never executed as SQL/shell; it is only ever stored as parameters.)"""
    redacted = redactor.redact(text).text
    return html.escape(strip_disallowed_links(redacted, allowed_domains), quote=False)


def validate_citations(cited: list[str], allowed_ids: set[str]) -> list[str]:
    """Keep only citations that reference chunks actually given to the model."""
    return [c for c in dict.fromkeys(cited) if c in allowed_ids]
