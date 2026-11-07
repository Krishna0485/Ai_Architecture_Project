"""Shared fixtures. The sample corpus is ingested once per session (real eCFR text)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from regintel.api.main import create_app
from regintel.audit.writer import InMemoryAuditWriter
from regintel.config import PROJECT_ROOT, Settings
from regintel.container import Container, build_container
from regintel.ingestion.pipeline import ingest_directory
from regintel.retrieval.base import Chunk, SecurityContext

SAMPLES = PROJECT_ROOT / "data" / "samples"
SYNTHETIC = PROJECT_ROOT / "data" / "synthetic"

ACME = {"X-API-Key": "dev-key-acme"}
GLOBEX = {"X-API-Key": "dev-key-globex"}


@pytest.fixture(scope="session")
def sample_chunks() -> list[Chunk]:
    return ingest_directory(SAMPLES)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        cache_backend="none",
        audit_backend="memory",
        check_executor="inline",
        index_path=tmp_path / "chunks.jsonl",
        audit_path=tmp_path / "audit.jsonl",
    )


@pytest.fixture
def container(settings: Settings, sample_chunks: list[Chunk]) -> Container:
    return build_container(settings, chunks=sample_chunks, audit=InMemoryAuditWriter())


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container=container)) as c:
        yield c


@pytest.fixture
def acme_ctx() -> SecurityContext:
    return SecurityContext("acme", ("compliance", "hr", "admin"), "acme-dev", "req1")


@pytest.fixture
def globex_ctx() -> SecurityContext:
    return SecurityContext("globex", ("compliance",), "globex-dev", "req2")


def synthetic(name: str) -> str:
    return (SYNTHETIC / name).read_text(encoding="utf-8")
