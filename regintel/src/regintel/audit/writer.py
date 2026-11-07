"""Audit writers. Details are PII-redacted before they are persisted."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol

from regintel.audit.models import AuditEvent
from regintel.config import Settings
from regintel.guardrails.pii import PIIRedactor, RegexPIIRedactor


class AuditWriter(Protocol):
    def write(self, event: AuditEvent) -> None: ...

    def query(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]: ...


def _redact(value: Any, redactor: PIIRedactor) -> Any:
    if isinstance(value, str):
        return redactor.redact(value).text
    if isinstance(value, dict):
        return {k: _redact(v, redactor) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, redactor) for v in value]
    return value


class InMemoryAuditWriter:
    def __init__(self, redactor: PIIRedactor | None = None) -> None:
        self.events: list[AuditEvent] = []
        self._redactor = redactor or RegexPIIRedactor()
        self._lock = threading.Lock()

    def write(self, event: AuditEvent) -> None:
        clean = event.model_copy(update={"details": _redact(event.details, self._redactor)})
        with self._lock:
            self.events.append(clean)

    def query(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        return [e for e in reversed(self.events) if e.tenant_id == tenant_id][:limit]


class JsonlAuditWriter:
    def __init__(self, path: Path, redactor: PIIRedactor | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._redactor = redactor or RegexPIIRedactor()
        self._lock = threading.Lock()

    def write(self, event: AuditEvent) -> None:
        clean = event.model_copy(update={"details": _redact(event.details, self._redactor)})
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(clean.model_dump_json() + "\n")

    def query(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    event = AuditEvent.model_validate(json.loads(line))
                    if event.tenant_id == tenant_id:
                        rows.append(event)
        return list(reversed(rows))[:limit]


def build_audit_writer(settings: Settings, redactor: PIIRedactor | None = None) -> AuditWriter:
    if settings.audit_backend == "postgres":  # pragma: no cover
        from regintel.storage.postgres import PostgresAuditWriter

        return PostgresAuditWriter(settings.postgres_dsn.get_secret_value())
    if settings.audit_backend == "memory":
        return InMemoryAuditWriter(redactor)
    return JsonlAuditWriter(settings.audit_path, redactor)
