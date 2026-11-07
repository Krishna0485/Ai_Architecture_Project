"""Chunkers. ``StructureAwareChunker`` is the default (see docs/adr/0001-chunking-strategy.md);
``FixedSizeChunker`` exists as the baseline for comparison."""

from __future__ import annotations

from typing import Protocol

from regintel.ingestion.models import Block, ParsedDocument, Section
from regintel.retrieval.base import Chunk
from regintel.text import count_tokens, sentences


class Chunker(Protocol):
    def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...


def _base_metadata(doc: ParsedDocument, section: Section) -> dict[str, str]:
    m = doc.meta
    return {
        "source": m.source,
        "act": m.act,
        "citation": m.citation,
        "jurisdiction": m.jurisdiction,
        "effective_date": m.effective_date,
        "version": m.version,
        "url": m.url,
        "tenant_id": m.tenant_id,
        "allowed_groups": ",".join(m.allowed_groups),
        "doc_type": m.doc_type,
        "section": section.section_id,
        "section_title": section.title,
        "heading_path": " > ".join(p for p in section.heading_path if p),
    }


def _split_long_text(text: str, max_tokens: int) -> list[str]:
    """Split an over-long paragraph on sentence boundaries; hard-split giant sentences."""
    pieces: list[str] = []
    buf: list[str] = []
    size = 0
    for sent in sentences(text) or [text]:
        n = count_tokens(sent)
        if n > max_tokens:
            words = sent.split()
            step = max(1, int(max_tokens / 1.3))
            for i in range(0, len(words), step):
                pieces.append(" ".join(words[i : i + step]))
            continue
        if size + n > max_tokens and buf:
            pieces.append(" ".join(buf))
            buf, size = [], 0
        buf.append(sent)
        size += n
    if buf:
        pieces.append(" ".join(buf))
    return pieces


class StructureAwareChunker:
    """Never crosses a section boundary; keeps tables whole; packs paragraphs up to
    ``max_tokens``; avoids tiny trailing chunks by merging remainders below ``min_tokens``;
    prepends the heading path so every chunk is self-describing."""

    def __init__(self, min_tokens: int = 300, max_tokens: int = 800) -> None:
        if min_tokens >= max_tokens:
            raise ValueError("min_tokens must be < max_tokens")
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens

    def _pack(self, blocks: list[Block], budget: int) -> list[list[str]]:
        groups: list[list[str]] = []
        cur: list[str] = []
        size = 0
        for block in blocks:
            if block.kind == "table":
                # Tables stay whole, even when larger than the budget.
                if cur:
                    groups.append(cur)
                    cur, size = [], 0
                groups.append([block.text])
                continue
            for piece in _split_long_text(block.text, budget):
                n = count_tokens(piece)
                if size + n > budget and cur:
                    groups.append(cur)
                    cur, size = [], 0
                cur.append(piece)
                size += n
        if cur:
            # Merge a small trailing remainder into the previous text group if it still fits.
            if (
                groups
                and size < self.min_tokens
                and sum(count_tokens(p) for p in groups[-1]) + size <= budget
                and not groups[-1][0].count(" | ")
            ):
                groups[-1].extend(cur)
            else:
                groups.append(cur)
        return groups

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        for section in doc.sections:
            header = " > ".join(p for p in section.heading_path if p)
            budget = max(50, self.max_tokens - count_tokens(header))
            for i, group in enumerate(self._pack(section.blocks, budget)):
                body = "\n".join(group).strip()
                if not body:
                    continue
                md = _base_metadata(doc, section) | {"chunk_index": str(i)}
                chunks.append(
                    Chunk(
                        id=f"{doc.meta.source}:{section.section_id}:{i}",
                        text=f"{header}\n{body}" if header else body,
                        metadata=md,
                    )
                )
        return chunks


class FixedSizeChunker:
    """Baseline: concatenates the whole document and cuts every ``size`` tokens with overlap.
    Section metadata is the section where the window *starts* (a known weakness)."""

    def __init__(self, size: int = 400, overlap: int = 50) -> None:
        if overlap >= size:
            raise ValueError("overlap must be < size")
        self.size = size
        self.overlap = overlap

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        words: list[tuple[str, Section]] = []
        for section in doc.sections:
            words.extend((w, section) for w in section.text.split())
        step_words = max(1, int((self.size - self.overlap) / 1.15))
        win_words = max(1, int(self.size / 1.15))
        chunks: list[Chunk] = []
        for n, start in enumerate(range(0, len(words), step_words)):
            window = words[start : start + win_words]
            if not window:
                break
            section = window[0][1]
            md = _base_metadata(doc, section) | {"chunk_index": str(n)}
            chunks.append(
                Chunk(
                    id=f"{doc.meta.source}:fixed:{n}",
                    text=" ".join(w for w, _ in window),
                    metadata=md,
                )
            )
        return chunks
