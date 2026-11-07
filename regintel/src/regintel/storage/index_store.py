"""Persisted chunk catalogue (JSONL). The source of truth the in-memory indexes are rebuilt from,
and the payload store that Qdrant/OpenSearch indexes mirror."""

from __future__ import annotations

import json
from pathlib import Path

from regintel.retrieval.base import Chunk


def save_chunks(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps({"id": c.id, "text": c.text, "metadata": c.metadata}) + "\n")


def load_chunks(path: Path) -> list[Chunk]:
    if not path.exists():
        return []
    chunks: list[Chunk] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                chunks.append(Chunk(row["id"], row["text"], dict(row["metadata"])))
    return chunks


class ChunkStore:
    """In-memory lookup of chunks by id and by section."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._by_id = {c.id: c for c in chunks}

    def __len__(self) -> int:
        return len(self._by_id)

    def all(self) -> list[Chunk]:
        return list(self._by_id.values())

    def get(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def by_section(self, section_id: str, source: str | None = None) -> list[Chunk]:
        out = [
            c
            for c in self._by_id.values()
            if c.section_id == section_id and (source is None or c.metadata.get("source") == source)
        ]
        return sorted(out, key=lambda c: int(c.metadata.get("chunk_index", "0")))
