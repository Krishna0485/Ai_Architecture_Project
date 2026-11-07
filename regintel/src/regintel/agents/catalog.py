"""Requirement catalogs per document type (data/catalog/*.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from regintel.agents.models import Requirement


@dataclass(frozen=True)
class Catalog:
    doc_type: str
    regulation_source: str
    requirements: tuple[Requirement, ...]


@lru_cache(maxsize=16)
def load_catalog(directory: Path, doc_type: str) -> Catalog:
    path = directory / f"{doc_type}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no requirement catalog for doc_type {doc_type!r}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Catalog(
        doc_type=raw["doc_type"],
        regulation_source=raw["regulation_source"],
        requirements=tuple(Requirement.model_validate(r) for r in raw["requirements"]),
    )


def available_doc_types(directory: Path) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.yaml"))
