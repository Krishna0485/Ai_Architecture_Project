"""Typed document model produced by parsers and consumed by chunkers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class SourceMetadata(BaseModel):
    """Metadata attached to every chunk of a source (see docs/data-sources.md)."""

    source: str  # stable document id, e.g. "16cfr314"
    act: str  # e.g. "GLBA Safeguards Rule"
    citation: str = ""  # e.g. "16 CFR Part 314"
    jurisdiction: str = "US-FED"
    effective_date: str = ""
    version: str = "1"
    url: str = ""
    licence: str = ""
    tenant_id: str = "public"
    allowed_groups: list[str] = Field(default_factory=lambda: ["*"])
    doc_type: str = "regulation"


@dataclass(frozen=True)
class Block:
    kind: Literal["text", "table"]
    text: str


@dataclass
class Section:
    """A structural unit (a regulation section or a document heading) with its heading path."""

    section_id: str
    title: str
    heading_path: list[str]
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass
class ParsedDocument:
    meta: SourceMetadata
    title: str
    sections: list[Section]
