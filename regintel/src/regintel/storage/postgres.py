"""PostgreSQL repositories (``stores`` extra): audit log and LangGraph checkpointer factory."""

from __future__ import annotations

import json
from typing import Any

from regintel.audit.models import AuditEvent

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    request_id TEXT, tenant_id TEXT NOT NULL, actor TEXT NOT NULL,
    action TEXT NOT NULL, resource TEXT, decision TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_events_tenant_ts ON audit_events (tenant_id, ts DESC);
"""


class PostgresAuditWriter:
    def __init__(self, dsn: str) -> None:
        import psycopg

        self._conn: Any = psycopg.connect(dsn, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(AUDIT_DDL)

    def write(self, event: AuditEvent) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_events (ts, request_id, tenant_id, actor, action, resource, "
                "decision, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    event.ts,
                    event.request_id,
                    event.tenant_id,
                    event.actor,
                    event.action,
                    event.resource,
                    event.decision,
                    json.dumps(event.details),
                ),
            )

    def query(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ts, request_id, tenant_id, actor, action, resource, decision, details "
                "FROM audit_events WHERE tenant_id = %s ORDER BY ts DESC LIMIT %s",
                (tenant_id, limit),
            )
            cols = [
                "ts",
                "request_id",
                "tenant_id",
                "actor",
                "action",
                "resource",
                "decision",
                "details",
            ]
            return [AuditEvent(**dict(zip(cols, row, strict=True))) for row in cur.fetchall()]


def postgres_checkpointer(dsn: str) -> Any:
    """LangGraph Postgres checkpointer: checks survive API restarts and resume after review."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row

    conn = Connection.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
