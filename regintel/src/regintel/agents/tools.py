"""Tools exposed to agents and the MCP server. Every tool: validates args (Pydantic), checks
policy against the caller's SecurityContext, and writes an audit event."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from regintel.agents.service import CheckService
from regintel.audit.models import AuditEvent
from regintel.audit.writer import AuditWriter
from regintel.generation.answer import AnswerService
from regintel.guardrails import PolicyDeniedError, PolicyEngine
from regintel.retrieval.base import MetadataFilter, SecurityContext


class SearchArgs(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    jurisdiction: str | None = Field(default=None, pattern=r"^[A-Z\-]{2,20}$")
    k: int = Field(default=5, ge=1, le=10)


class CheckArgs(BaseModel):
    document_id: str = Field(pattern=r"^doc_[0-9a-f]{12}$")


class ChecklistArgs(BaseModel):
    section_id: str = Field(pattern=r"^\d{1,4}(\.\d{1,4})?[a-z]?$")
    source: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,40}$")


class ToolError(RuntimeError):
    pass


class RegIntelTools:
    def __init__(
        self, answers: AnswerService, checks: CheckService, policy: PolicyEngine, audit: AuditWriter
    ) -> None:
        self.answers = answers
        self.checks = checks
        self.policy = policy
        self.audit = audit

    def _guard(self, ctx: SecurityContext, action: str, args: dict[str, Any]) -> None:
        decision = self.policy.decide(ctx, action)
        self.audit.write(
            AuditEvent(
                request_id=ctx.request_id,
                tenant_id=ctx.tenant_id,
                actor=ctx.actor,
                action=f"tool:{action}",
                decision="allow" if decision.allowed else "deny",
                details={"args": args, "reason": decision.reason},
            )
        )
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason)

    @staticmethod
    def _validate(model: type[BaseModel], raw: dict[str, Any]) -> Any:
        try:
            return model.model_validate(raw)
        except ValidationError as exc:
            raise ToolError(f"invalid arguments: {exc.errors(include_url=False)}") from exc

    def search_regulations(self, ctx: SecurityContext, **raw: Any) -> dict[str, Any]:
        args: SearchArgs = self._validate(SearchArgs, raw)
        self._guard(ctx, "search_regulations", args.model_dump())
        filters = MetadataFilter(jurisdiction=args.jurisdiction) if args.jurisdiction else None
        hits = self.answers.retrieval.search(args.query, ctx, filters)[: args.k]
        return {
            "results": [
                {
                    "chunk_id": h.chunk.id,
                    "citation": h.chunk.metadata.get("citation", ""),
                    "section": h.chunk.section_id,
                    "title": h.chunk.metadata.get("section_title", ""),
                    "url": h.chunk.metadata.get("url", ""),
                    "score": round(h.score, 4),
                    "text": h.chunk.text[:1200],
                }
                for h in hits
            ]
        }

    def ask(self, ctx: SecurityContext, question: str) -> dict[str, Any]:
        args: SearchArgs = self._validate(SearchArgs, {"query": question})
        self._guard(ctx, "ask", {"question": args.query})
        return self.answers.answer(args.query, ctx).model_dump()

    def check_document(self, ctx: SecurityContext, **raw: Any) -> dict[str, Any]:
        args: CheckArgs = self._validate(CheckArgs, raw)
        self._guard(ctx, "check_document", args.model_dump())
        return self.checks.start(args.document_id, ctx).model_dump()

    def get_check(self, ctx: SecurityContext, check_id: str) -> dict[str, Any]:
        self._guard(ctx, "check_document", {"check_id": check_id})
        return self.checks.get(check_id, ctx).model_dump()

    def get_checklist(self, ctx: SecurityContext, **raw: Any) -> dict[str, Any]:
        args: ChecklistArgs = self._validate(ChecklistArgs, raw)
        self._guard(ctx, "get_checklist", args.model_dump())
        return self.checks.checklist(args.section_id, ctx, args.source).model_dump()
