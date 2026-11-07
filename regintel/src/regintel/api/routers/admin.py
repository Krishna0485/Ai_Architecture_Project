"""Health, readiness, metrics and audit endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from regintel import __version__
from regintel.api.deps import ContainerDep, CtxDep, authorize
from regintel.audit.models import AuditEvent
from regintel.observability.metrics import render_latest

router = APIRouter(tags=["admin"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready")
def ready(container: ContainerDep) -> dict[str, Any]:
    n = len(container.chunks)
    return {
        "status": "ready" if n else "not_ready",
        "chunks": n,
        "retrieval": container.retrieval.config.key,
        "llm_provider": container.settings.llm_provider,
        "agents_enabled": container.settings.agents_enabled,
    }


@router.get("/metrics")
def prometheus_metrics() -> Response:
    return Response(render_latest(), media_type="text/plain; version=0.0.4")


@router.get("/v1/admin/audit", response_model=list[AuditEvent])
def audit_log(container: ContainerDep, ctx: CtxDep, limit: int = 100) -> list[AuditEvent]:
    authorize(container, ctx, "read_audit")
    return container.audit.query(ctx.tenant_id, min(max(limit, 1), 500))
