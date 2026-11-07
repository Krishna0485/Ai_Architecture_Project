"""Audit event model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str = ""
    tenant_id: str
    actor: str
    action: str
    resource: str = ""
    decision: Literal["allow", "deny", "error", "info"] = "allow"
    details: dict[str, Any] = Field(default_factory=dict)
