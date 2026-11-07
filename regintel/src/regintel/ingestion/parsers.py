"""Parsers: eCFR XML (native structure), Markdown/plain text, and PDF/HTML via Docling."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from regintel.ingestion.models import Block, ParsedDocument, Section, SourceMetadata

_WS = re.compile(r"\s+")
_SECTION_NUM = re.compile("§+\\s*([\\d.\\-–]+[a-z]?)")  # noqa: RUF001 - en dash appears in eCFR section ranges


def _clean(text: str) -> str:
    return _WS.sub(" ", html.unescape(text)).strip()


def _itertext(el: ET.Element) -> str:
    return _clean("".join(el.itertext()))


def _table_to_text(el: ET.Element) -> str:
    rows: list[str] = []
    for tr in el.iter():
        if tr.tag in ("ROW", "TR", "BOXHD"):
            cells = [_itertext(c) for c in tr if c.tag in ("ENT", "TD", "TH", "CHED")]
            if cells:
                rows.append(" | ".join(cells))
    return "\n".join(rows) if rows else _itertext(el)


def parse_ecfr_xml(path: Path, meta: SourceMetadata) -> ParsedDocument:
    """Parse eCFR "full" XML. DIV5=part, DIV6=subpart, DIV8=section, DIV9=appendix."""
    root = ET.parse(path).getroot()  # noqa: S314 - trusted government source, no DTD processing
    root_head = root.find("HEAD")
    part_head = _itertext(root_head) if root_head is not None else meta.citation
    sections: list[Section] = []

    def walk(el: ET.Element, path_titles: list[str]) -> None:
        for child in el:
            if child.tag in ("DIV6", "DIV7"):
                sub_head = child.find("HEAD")
                walk(child, [*path_titles, _itertext(sub_head) if sub_head is not None else ""])
            elif child.tag in ("DIV8", "DIV9"):
                head_el = child.find("HEAD")
                head: str = _itertext(head_el) if head_el is not None else child.get("N", "")
                if "[Reserved]" in head:
                    continue
                m = _SECTION_NUM.search(head)
                section_id = m.group(1) if m else (child.get("N") or head)
                title = _SECTION_NUM.sub("", head).strip(" .") or head
                blocks: list[Block] = []
                for node in child:
                    if node.tag in ("P", "FP", "NOTE", "EXTRACT"):
                        txt = _itertext(node)
                        if txt:
                            blocks.append(Block("text", txt))
                    elif node.tag in ("GPOTABLE", "TABLE"):
                        blocks.append(Block("table", _table_to_text(node)))
                if blocks:
                    sections.append(
                        Section(
                            section_id, title, [*path_titles, f"§ {section_id} {title}"], blocks
                        )
                    )

    walk(root, [part_head])
    return ParsedDocument(meta=meta, title=part_head, sections=sections)


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_markdown(text: str, meta: SourceMetadata) -> ParsedDocument:
    """Split Markdown into sections by heading; tables (``|`` rows) are kept as whole blocks."""
    title = meta.act
    stack: list[str] = []
    sections: list[Section] = []
    current: Section | None = None
    para: list[str] = []
    table: list[str] = []

    def flush() -> None:
        nonlocal para, table
        if current is None:
            para, table = [], []
            return
        if para:
            current.blocks.append(Block("text", _clean(" ".join(para))))
        if table:
            current.blocks.append(Block("table", "\n".join(table)))
        para, table = [], []

    counter = 0
    for line in text.splitlines():
        heading = _MD_HEADING.match(line)
        if heading:
            flush()
            level, head = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not sections and current is None:
                title = head
            stack = [*stack[: level - 1], head]
            counter += 1
            m = re.match(r"^(\d+(?:\.\d+)*)[.)]?\s+", head)
            section_id = m.group(1) if m else f"s{counter}"
            current = Section(section_id, head, [title, *stack[1:]] if level > 1 else [title])
            sections.append(current)
            continue
        stripped = line.strip()
        if stripped.startswith("|"):
            if para:
                flush()
            if not set(stripped) <= set("|-: "):
                table.append(stripped)
        elif not stripped:
            flush()
        else:
            if table:
                flush()
            para.append(stripped)
    flush()
    if not sections:
        sections = [Section("s1", title, [title], [Block("text", _clean(text))])]
    return ParsedDocument(meta=meta, title=title, sections=[s for s in sections if s.blocks])


def parse_with_docling(path: Path, meta: SourceMetadata) -> ParsedDocument:  # pragma: no cover
    """PDF/HTML/DOCX via Docling (optional ``ml`` extra). Docling preserves tables and headings;
    we export to Markdown and reuse the Markdown sectioniser."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError("Docling not installed: uv sync --extra ml") from exc
    result = DocumentConverter().convert(str(path))
    return parse_markdown(result.document.export_to_markdown(), meta)


def parse_file(path: Path, meta: SourceMetadata) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return parse_ecfr_xml(path, meta)
    if suffix in (".md", ".txt"):
        return parse_markdown(path.read_text(encoding="utf-8"), meta)
    return parse_with_docling(path, meta)
