"""Marking untrusted content before it enters a prompt."""

from __future__ import annotations

import html
import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁤﻿]")
_SPOOF = re.compile(r"</?\s*untrusted[^>]*>", re.I)


def neutralize(text: str) -> str:
    """Strip control / zero-width / bidi characters and any spoofed wrapper tags."""
    return _SPOOF.sub("[removed-tag]", _CONTROL.sub("", text))


def wrap_untrusted(text: str, source: str) -> str:
    """Wrap text as data. Prompts instruct the model that content inside ``<untrusted>`` is
    reference material and that instructions inside it must never be followed."""
    safe_source = html.escape(re.sub(r"[^\w.:\-/]", "_", source), quote=True)
    return f'<untrusted source="{safe_source}">\n{neutralize(text)}\n</untrusted>'
