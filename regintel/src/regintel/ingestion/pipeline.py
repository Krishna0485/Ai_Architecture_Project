"""Ingestion pipeline: manifest -> parse -> chunk -> persist -> index.

Usage: ``python -m regintel.ingestion.pipeline --source data/samples``
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from regintel.config import Settings, get_settings
from regintel.ingestion.chunker import Chunker, StructureAwareChunker
from regintel.ingestion.models import SourceMetadata
from regintel.ingestion.parsers import parse_file
from regintel.retrieval.base import Chunk
from regintel.storage.index_store import save_chunks

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManifestEntry:
    path: Path
    meta: SourceMetadata


def load_manifest(source_dir: Path) -> list[ManifestEntry]:
    """Read ``sources.yaml`` from the source directory (see docs/data-sources.md)."""
    manifest = source_dir / "sources.yaml"
    if not manifest.exists():
        raise FileNotFoundError(f"missing manifest {manifest}")
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    entries: list[ManifestEntry] = []
    for item in raw.get("sources", []):
        file = source_dir / item.pop("file")
        if not file.exists():
            log.warning("skipping missing source file %s", file)
            continue
        entries.append(ManifestEntry(file, SourceMetadata(**item)))
    return entries


def ingest_directory(source_dir: Path, chunker: Chunker | None = None) -> list[Chunk]:
    """Parse and chunk every source listed in the manifest. Pure (no I/O besides reads)."""
    chunker = chunker or StructureAwareChunker()
    chunks: list[Chunk] = []
    for entry in load_manifest(source_dir):
        doc = parse_file(entry.path, entry.meta)
        doc_chunks = chunker.chunk(doc)
        log.info(
            "%s: %d sections -> %d chunks", entry.meta.source, len(doc.sections), len(doc_chunks)
        )
        chunks.extend(doc_chunks)
    ids = [c.id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate chunk ids produced; check manifest for duplicate sources")
    return chunks


def index_chunks(chunks: list[Chunk], settings: Settings) -> None:
    """Persist the chunk catalogue and mirror to external stores when configured."""
    save_chunks(chunks, settings.index_path)
    if settings.vector_store == "qdrant":  # pragma: no cover - needs docker services
        from regintel.retrieval.factory import build_embedder
        from regintel.storage.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(
            settings.qdrant_url, settings.qdrant_collection, settings.embedding_dim
        )
        store.upsert(chunks, build_embedder(settings).embed([c.text for c in chunks]))
    if settings.keyword_store == "opensearch":  # pragma: no cover - needs docker services
        from regintel.storage.opensearch_store import OpenSearchKeywordStore

        OpenSearchKeywordStore(settings.opensearch_url, settings.opensearch_index).index(chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest regulation sources")
    parser.add_argument("--source", type=Path, default=Path("data/samples"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    chunker = StructureAwareChunker(settings.chunk_min_tokens, settings.chunk_max_tokens)
    chunks = ingest_directory(args.source, chunker)
    index_chunks(chunks, settings)
    log.info("indexed %d chunks -> %s", len(chunks), settings.index_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
