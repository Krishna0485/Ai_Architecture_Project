"""Uploaded-document repository. Text is stored PII-redacted; injection scan results are kept
alongside so reviewers can see why lines were quarantined."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class StoredDocument(BaseModel):
    id: str
    tenant_id: str
    filename: str
    text: str
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    pii_entities: int = 0
    injection_score: float = 0.0
    injection_signals: list[str] = Field(default_factory=list)


class DocumentRepository:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self._docs: dict[str, StoredDocument] = {}
        self._lock = threading.Lock()
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            for p in directory.glob("*.json"):
                doc = StoredDocument.model_validate(json.loads(p.read_text(encoding="utf-8")))
                self._docs[doc.id] = doc

    def add(
        self,
        tenant_id: str,
        filename: str,
        text: str,
        *,
        pii_entities: int = 0,
        injection_score: float = 0.0,
        injection_signals: list[str] | None = None,
    ) -> StoredDocument:
        doc = StoredDocument(
            id="doc_" + uuid.uuid4().hex[:12],
            tenant_id=tenant_id,
            filename=filename[:200],
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            pii_entities=pii_entities,
            injection_score=injection_score,
            injection_signals=injection_signals or [],
        )
        with self._lock:
            self._docs[doc.id] = doc
            if self.directory is not None:
                (self.directory / f"{doc.id}.json").write_text(
                    doc.model_dump_json(), encoding="utf-8"
                )
        return doc

    def get(self, doc_id: str, tenant_id: str) -> StoredDocument | None:
        """Tenant-scoped lookup: another tenant's document is indistinguishable from missing."""
        doc = self._docs.get(doc_id)
        return doc if doc is not None and doc.tenant_id == tenant_id else None

    def list(self, tenant_id: str) -> list[StoredDocument]:
        return [d for d in self._docs.values() if d.tenant_id == tenant_id]
