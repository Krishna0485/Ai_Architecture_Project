"""Documents, compliance checks (with human review) and checklist generation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from regintel.agents.models import ChecklistResult, ReviewDecision
from regintel.agents.service import (
    AgentsDisabledError,
    CheckConflictError,
    CheckNotFoundError,
    CheckView,
)
from regintel.api.deps import ContainerDep, CtxDep, authorize
from regintel.audit.models import AuditEvent
from regintel.observability import metrics

router = APIRouter(prefix="/v1", tags=["checks"])
MAX_DOC_CHARS = 200_000


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=20, max_length=MAX_DOC_CHARS)


class UploadResponse(BaseModel):
    document_id: str
    pii_entities_redacted: int
    injection_score: float
    injection_signals: list[str]


class StartCheckRequest(BaseModel):
    document_id: str = Field(pattern=r"^doc_[0-9a-f]{12}$")


class ChecklistRequest(BaseModel):
    section_id: str = Field(pattern=r"^\d{1,4}(\.\d{1,4})?[a-z]?$")
    source: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,40}$")


def _disabled() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent workflows disabled")


@router.post("/documents", response_model=UploadResponse, status_code=201)
def upload_document(req: UploadRequest, container: ContainerDep, ctx: CtxDep) -> UploadResponse:
    authorize(container, ctx, "upload_document")
    redacted = container.redactor.redact(req.text)
    scan = container.scanner.scan(redacted.text)
    if scan.is_suspicious:
        metrics.GUARDRAIL_BLOCKS.labels("injection", "flag_upload").inc()
    doc = container.documents.add(
        ctx.tenant_id,
        req.filename,
        redacted.text,
        pii_entities=len(redacted.entities),
        injection_score=scan.score,
        injection_signals=scan.signals,
    )
    container.audit.write(
        AuditEvent(
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            actor=ctx.actor,
            action="upload_document",
            resource=doc.id,
            details={
                "filename": req.filename,
                "pii_entities": len(redacted.entities),
                "injection_signals": scan.signals,
            },
        )
    )
    return UploadResponse(
        document_id=doc.id,
        pii_entities_redacted=len(redacted.entities),
        injection_score=scan.score,
        injection_signals=scan.signals,
    )


@router.post("/checks", response_model=CheckView, status_code=202)
def start_check(req: StartCheckRequest, container: ContainerDep, ctx: CtxDep) -> CheckView:
    authorize(container, ctx, "check_document")
    try:
        return container.checks.start(req.document_id, ctx)
    except CheckNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found") from exc
    except AgentsDisabledError as exc:
        raise _disabled() from exc


@router.get("/checks/{check_id}", response_model=CheckView)
def get_check(check_id: str, container: ContainerDep, ctx: CtxDep) -> CheckView:
    authorize(container, ctx, "check_document")
    try:
        return container.checks.get(check_id, ctx)
    except CheckNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "check not found") from exc


@router.post("/checks/{check_id}/review", response_model=CheckView)
def review_check(
    check_id: str, decision: ReviewDecision, container: ContainerDep, ctx: CtxDep
) -> CheckView:
    authorize(container, ctx, "review_check")
    try:
        return container.checks.review(check_id, decision, ctx)
    except CheckNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "check not found") from exc
    except CheckConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except AgentsDisabledError as exc:
        raise _disabled() from exc


@router.post("/checklists", response_model=ChecklistResult)
def checklist(req: ChecklistRequest, container: ContainerDep, ctx: CtxDep) -> ChecklistResult:
    authorize(container, ctx, "get_checklist")
    try:
        result = container.checks.checklist(req.section_id, ctx, req.source)
    except AgentsDisabledError as exc:
        raise _disabled() from exc
    if not result.checklist and result.errors:
        raise HTTPException(status.HTTP_404_NOT_FOUND, result.errors[0])
    return result
