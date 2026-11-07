"""Runs compliance checks and checklist generation; the API and MCP server call this."""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from regintel.agents.deps import AgentDeps
from regintel.agents.graphs.checklist import build_checklist_graph
from regintel.agents.graphs.compliance_check import build_compliance_graph
from regintel.agents.models import ChecklistResult, ReviewDecision
from regintel.agents.nodes.checklist import ChecklistNodes
from regintel.agents.nodes.compliance import ComplianceNodes
from regintel.audit.models import AuditEvent
from regintel.audit.writer import AuditWriter
from regintel.retrieval.base import SecurityContext
from regintel.storage.documents import DocumentRepository

log = logging.getLogger(__name__)
CheckStatus = Literal["queued", "running", "awaiting_review", "completed", "rejected", "failed"]


class CheckNotFoundError(KeyError):
    pass


class CheckConflictError(RuntimeError):
    pass


class AgentsDisabledError(RuntimeError):
    pass


class CheckView(BaseModel):
    check_id: str
    document_id: str
    status: CheckStatus
    doc_type: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    pending_review: dict[str, Any] | None = None


class CheckService:
    def __init__(
        self,
        deps: AgentDeps,
        documents: DocumentRepository,
        audit: AuditWriter,
        *,
        checkpointer: Any | None = None,
        executor: Literal["inline", "background", "queue"] = "background",
        enabled: bool = True,
        queue: Any | None = None,
    ) -> None:
        self.deps = deps
        self.documents = documents
        self.audit = audit
        self.executor = executor
        self.enabled = enabled
        self.queue = queue
        self.graph = build_compliance_graph(ComplianceNodes(deps), checkpointer or MemorySaver())
        self.checklist_graph = build_checklist_graph(ChecklistNodes(deps))
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="check")
        self._futures: dict[str, Future[None]] = {}
        self._owners: dict[str, tuple[str, str]] = {}  # check_id -> (tenant, document)
        self._lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------------------
    def _config(self, check_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": check_id}, "recursion_limit": self.deps.max_steps}

    def _run(self, check_id: str, graph_input: Any) -> None:
        try:
            self.graph.invoke(graph_input, self._config(check_id))
        except Exception as exc:  # pragma: no cover - defensive: surfaced via status
            log.exception("check %s crashed", check_id)
            self.graph.update_state(
                self._config(check_id), {"status": "failed", "errors": [f"crash: {exc}"]}
            )

    def _dispatch(self, check_id: str, graph_input: Any) -> None:
        if self.executor == "inline":
            self._run(check_id, graph_input)
        elif self.executor == "queue" and self.queue is not None:  # pragma: no cover
            self.queue.enqueue(check_id, graph_input)
        else:
            self._futures[check_id] = self._pool.submit(self._run, check_id, graph_input)

    def _audit(
        self,
        ctx: SecurityContext,
        action: str,
        resource: str,
        decision: Literal["allow", "deny", "error", "info"] = "allow",
        **details: Any,
    ) -> None:
        self.audit.write(
            AuditEvent(
                request_id=ctx.request_id,
                tenant_id=ctx.tenant_id,
                actor=ctx.actor,
                action=action,
                resource=resource,
                decision=decision,
                details=details,
            )
        )

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise AgentsDisabledError("agent workflows are disabled (kill switch)")

    # -- public API ------------------------------------------------------------------------
    def start(self, document_id: str, ctx: SecurityContext) -> CheckView:
        self._require_enabled()
        doc = self.documents.get(document_id, ctx.tenant_id)
        if doc is None:
            raise CheckNotFoundError(document_id)
        check_id = "chk_" + uuid.uuid4().hex[:12]
        with self._lock:
            self._owners[check_id] = (ctx.tenant_id, document_id)
        state = {
            "check_id": check_id,
            "document_id": document_id,
            "tenant_id": ctx.tenant_id,
            "groups": list(ctx.groups),
            "actor": ctx.actor,
            "document_text": doc.text,
            "status": "running",
            "steps": 0,
            "errors": [],
        }
        self._audit(ctx, "check_document", check_id, document_id=document_id)
        self._dispatch(check_id, state)
        return CheckView(
            check_id=check_id,
            document_id=document_id,
            status="queued" if self.executor != "inline" else self.get(check_id, ctx).status,
        )

    def wait(self, check_id: str, timeout: float = 30.0) -> None:
        fut = self._futures.get(check_id)
        if fut is not None:
            fut.result(timeout=timeout)

    def get(self, check_id: str, ctx: SecurityContext) -> CheckView:
        snapshot = self.graph.get_state(self._config(check_id))
        values: dict[str, Any] = dict(snapshot.values or {})
        owner = values.get("tenant_id") or self._owners.get(check_id, ("", ""))[0]
        if not owner or owner != ctx.tenant_id:
            raise CheckNotFoundError(check_id)  # do not reveal other tenants' checks
        pending = None
        for task in snapshot.tasks or ():
            if task.interrupts:
                pending = dict(task.interrupts[0].value)
        status: str = values.get("status", "queued")
        fut = self._futures.get(check_id)
        if fut is not None and not fut.done() and pending is None:
            status = "running"
        if pending is not None:
            status = "awaiting_review"
        return CheckView(
            check_id=check_id,
            document_id=values.get("document_id", ""),
            status=status,  # type: ignore[arg-type]
            doc_type=values.get("doc_type"),
            findings=values.get("findings", []),
            report=values.get("report"),
            errors=values.get("errors", []),
            pending_review=pending,
        )

    def review(self, check_id: str, decision: ReviewDecision, ctx: SecurityContext) -> CheckView:
        self._require_enabled()
        view = self.get(check_id, ctx)
        if view.status != "awaiting_review":
            raise CheckConflictError(f"check {check_id} is {view.status}, not awaiting_review")
        known = {f["id"] for f in view.findings}
        unknown = [c.finding_id for c in decision.corrections if c.finding_id not in known]
        if unknown:
            raise ValueError(f"unknown finding ids: {unknown}")
        decision = decision.model_copy(update={"reviewer": ctx.actor})  # identity from auth only
        self._audit(
            ctx,
            "review_check",
            check_id,
            review_decision=decision.decision,
            corrections=len(decision.corrections),
        )
        self._dispatch(check_id, Command(resume=decision.model_dump()))
        if self.executor == "background":
            self.wait(check_id)
        return self.get(check_id, ctx)

    def checklist(
        self, section_id: str, ctx: SecurityContext, source: str | None = None
    ) -> ChecklistResult:
        self._require_enabled()
        out = self.checklist_graph.invoke(
            {
                "section_id": section_id,
                "source": source or "",
                "tenant_id": ctx.tenant_id,
                "groups": list(ctx.groups),
                "errors": [],
            }
        )
        self._audit(ctx, "get_checklist", section_id, items=len(out.get("checklist", [])))
        return ChecklistResult(
            section_id=section_id,
            source=out.get("source", ""),
            citations=out.get("citations", []),
            checklist=out.get("checklist", []),
            tests=out.get("tests", []),
            errors=out.get("errors", []),
        )
