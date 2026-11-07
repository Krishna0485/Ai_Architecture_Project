from __future__ import annotations

from pathlib import Path

import pytest

from regintel.ingestion.chunker import FixedSizeChunker, StructureAwareChunker
from regintel.ingestion.models import Block, SourceMetadata
from regintel.ingestion.parsers import parse_ecfr_xml, parse_file, parse_markdown
from regintel.ingestion.pipeline import index_chunks, ingest_directory, load_manifest, main
from regintel.storage.index_store import ChunkStore, load_chunks
from regintel.text import count_tokens
from tests.fixtures.fakes import ECFR_XML, make_doc

META = SourceMetadata(source="t999", act="Test", citation="99 CFR 999")


def test_parse_ecfr_xml_sections_tables_and_reserved(tmp_path: Path) -> None:
    p = tmp_path / "t.xml"
    p.write_text(ECFR_XML, encoding="utf-8")
    doc = parse_ecfr_xml(p, META)
    ids = [s.section_id for s in doc.sections]
    assert ids == ["999.1", "999.3"]  # reserved section skipped
    assert doc.sections[0].heading_path[-1] == "§ 999.1 Purpose"
    assert "Subpart A" in doc.sections[0].heading_path[1]
    kinds = [b.kind for b in doc.sections[1].blocks]
    assert kinds == ["text", "table"]
    assert "Widget | $5" in doc.sections[1].blocks[1].text


def test_parse_markdown_headings_tables_and_ids() -> None:
    md = (
        "# Policy\n\nintro text\n\n## 1. Scope\nApplies to all.\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n## Notes\nfree text\n"
    )
    doc = parse_markdown(md, META)
    assert doc.title == "Policy"
    by_id = {s.section_id: s for s in doc.sections}
    assert "1" in by_id and by_id["1"].blocks[1].kind == "table"
    assert any(s.title == "Notes" for s in doc.sections)


def test_parse_markdown_without_headings_falls_back() -> None:
    doc = parse_markdown("just text", META)
    assert len(doc.sections) == 1 and doc.sections[0].text == "just text"


def test_parse_file_dispatch(tmp_path: Path) -> None:
    md = tmp_path / "a.md"
    md.write_text("# T\n## 1. A\nbody", encoding="utf-8")
    assert parse_file(md, META).sections[0].section_id == "1"


def test_structure_chunker_never_crosses_sections_and_prepends_headings() -> None:
    doc = make_doc(
        [
            ("1.1", "Alpha", [Block("text", "alpha " * 50)]),
            ("1.2", "Beta", [Block("text", "beta " * 50)]),
        ]
    )
    chunks = StructureAwareChunker(50, 200).chunk(doc)
    assert [c.section_id for c in chunks] == ["1.1", "1.2"]
    assert chunks[0].text.startswith("Test Act > § 1.1 Alpha\n")
    assert chunks[0].id == "testdoc:1.1:0"
    assert chunks[0].metadata["allowed_groups"] == "*"


def test_structure_chunker_splits_long_sections_within_budget() -> None:
    sentences = " ".join(f"Sentence number {i} explains a rule." for i in range(300))
    doc = make_doc([("2.1", "Long", [Block("text", sentences)])])
    chunks = StructureAwareChunker(100, 300).chunk(doc)
    assert len(chunks) > 3
    assert all(count_tokens(c.text) <= 300 + 20 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_structure_chunker_keeps_tables_whole_even_if_large() -> None:
    table = "\n".join(f"row{i} | value{i} | more{i}" for i in range(400))
    doc = make_doc([("3.1", "Table", [Block("text", "Intro."), Block("table", table)])])
    chunks = StructureAwareChunker(50, 200).chunk(doc)
    table_chunks = [c for c in chunks if "row0 |" in c.text]
    assert len(table_chunks) == 1 and "row399 |" in table_chunks[0].text


def test_structure_chunker_handles_empty_heading_and_giant_sentence() -> None:
    doc = make_doc([("4.1", "", [Block("text", "word " * 2000)])])
    doc.sections[0].heading_path = ["", ""]
    chunks = StructureAwareChunker(100, 300).chunk(doc)
    assert len(chunks) >= 5
    assert not chunks[0].text.startswith(" > ")


def test_structure_chunker_merges_small_tail() -> None:
    doc = make_doc([("5.1", "Tail", [Block("text", "a " * 150), Block("text", "tail words")])])
    chunks = StructureAwareChunker(100, 400).chunk(doc)
    assert len(chunks) == 1 and "tail words" in chunks[0].text


def test_chunker_validation() -> None:
    with pytest.raises(ValueError):
        StructureAwareChunker(500, 400)
    with pytest.raises(ValueError):
        FixedSizeChunker(100, 100)


def test_fixed_size_chunker_windows() -> None:
    doc = make_doc([("1", "A", [Block("text", "x " * 1000)])])
    chunks = FixedSizeChunker(200, 20).chunk(doc)
    assert len(chunks) > 4 and chunks[0].id == "testdoc:fixed:0"


def test_ingest_sample_corpus(sample_chunks: list) -> None:  # type: ignore[type-arg]
    sources = {c.metadata["source"] for c in sample_chunks}
    assert {"16cfr314", "29cfr825", "12cfr1002", "acme_internal_guidance"} <= sources
    sec = [c for c in sample_chunks if c.section_id == "314.4"]
    assert sec and all(c.metadata["citation"] == "16 CFR Part 314" for c in sec)
    acme = [c for c in sample_chunks if c.metadata["source"] == "acme_internal_guidance"]
    assert acme[0].tenant_id == "acme" and "compliance" in acme[0].allowed_groups


def test_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path)


def test_manifest_skips_missing_files_and_detects_duplicates(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A\n## 1. X\nbody text here", encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(
        "sources:\n- {file: a.md, source: a, act: A}\n- {file: missing.md, source: b, act: B}\n"
        "- {file: a.md, source: a, act: A}\n",
        encoding="utf-8",
    )
    assert len(load_manifest(tmp_path)) == 2
    with pytest.raises(ValueError, match="duplicate"):
        ingest_directory(tmp_path)


def test_index_and_cli_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list
) -> None:  # type: ignore[type-arg]
    from regintel.config import Settings

    s = Settings(index_path=tmp_path / "idx.jsonl")
    index_chunks(sample_chunks[:5], s)
    loaded = load_chunks(s.index_path)
    assert [c.id for c in loaded] == [c.id for c in sample_chunks[:5]]
    store = ChunkStore(loaded)
    assert store.get(loaded[0].id) == loaded[0] and len(store) == 5
    assert load_chunks(tmp_path / "nope.jsonl") == []
    monkeypatch.setenv("REGINTEL_INDEX_PATH", str(tmp_path / "cli.jsonl"))
    from regintel.config import get_settings

    get_settings.cache_clear()
    try:
        from regintel.config import PROJECT_ROOT

        assert main(["--source", str(PROJECT_ROOT / "data" / "samples")]) == 0
        assert len(load_chunks(tmp_path / "cli.jsonl")) == len(sample_chunks)
    finally:
        get_settings.cache_clear()
