"""Nodes of the ``compliance_check`` graph.

Trust boundary (quarantine pattern):
  * ``classify_document`` and ``extract_obligations`` are the only nodes that read the untrusted
    document. They call tool-less models and their outputs are schema-validated.
  * All later nodes see only validated ``facts`` - never raw document text - so an instruction
    hidden in an upload cannot reach a privileged step or change the requirement set.
"""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Callable
from typing import Any

from langgraph.types import interrupt

from regintel.agents.catalog import load_catalog
from regintel.agents.deps import AgentDeps
from regintel.agents.models import (
    Classification,
    Comparison,
    DocumentFacts,
    Finding,
    Requirement,
    ReviewDecision,
)
from regintel.agents.state import ComplianceState
from regintel.guardrails import OutputValidationError, parse_structured, wrap_untrusted
from regintel.llm.base import LLMError, LLMRequest
from regintel.observability import metrics
from regintel.observability.tracing import span
from regintel.retrieval.base import MetadataFilter, SecurityContext
from regintel.text import content_terms

log = logging.getLogger(__name__)
Method = Callable[["ComplianceNodes", ComplianceState], dict[str, Any]]


def guarded(name: str) -> Callable[[Method], Method]:
    """Count steps, enforce the step limit, trace, and convert exceptions to state errors."""

    def deco(fn: Method) -> Method:
        @functools.wraps(fn)
        def wrapper(self: ComplianceNodes, state: ComplianceState) -> dict[str, Any]:
            steps = state.get("steps", 0) + 1
            limit = self.d.max_steps
            if steps > limit:
                return {
                    "steps": steps,
                    "errors": [*state.get("errors", []), f"step limit {limit} exceeded at {name}"],
                }
            with span(f"agent.{name}", check_id=state.get("check_id")):
                try:
                    update = fn(self, state)
                except (LLMError, OutputValidationError, FileNotFoundError, ValueError) as exc:
                    log.warning("node %s failed: %s", name, exc)
                    return {"steps": steps, "errors": [*state.get("errors", []), f"{name}: {exc}"]}
            return {**update, "steps": steps}

        return wrapper

    return deco


class ComplianceNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.d = deps

    def _llm(
        self,
        task: str,
        prompt_id: str,
        state: ComplianceState,
        *,
        inputs: dict[str, Any],
        **variables: object,
    ) -> str:
        system, user = self.d.prompts.render(prompt_id, **variables)
        resp = self.d.gateway.complete(
            LLMRequest(
                task=task,
                prompt_id=prompt_id,
                system=system,
                user=user,
                inputs=inputs,
                json_mode=True,
                max_tokens=1500,
                tenant_id=state.get("tenant_id", "public"),
            )
        )
        return resp.text

    # -- quarantined nodes (read untrusted text, no tools, schema-validated output) -----------
    @guarded("classify_document")
    def classify_document(self, state: ComplianceState) -> dict[str, Any]:
        text = state["document_text"][:6000]
        raw = self._llm(
            "classify_document",
            "classify_document.v1",
            state,
            inputs={"text": text},
            document=wrap_untrusted(text, "upload"),
        )
        c = parse_structured(raw, Classification)
        return {
            "doc_type": c.doc_type,
            "classification_confidence": c.confidence,
            "status": "running",
        }

    @guarded("extract_obligations")
    def extract_obligations(self, state: ComplianceState) -> dict[str, Any]:
        clean, quarantined = self.d.scanner.split_suspicious(state["document_text"])
        if quarantined:
            metrics.GUARDRAIL_BLOCKS.labels("injection", "quarantine_lines").inc(len(quarantined))
        raw = self._llm(
            "extract_facts",
            "extract_facts.v1",
            state,
            inputs={"text": clean},
            document=wrap_untrusted(clean, "upload"),
        )
        facts = parse_structured(raw, DocumentFacts)
        # Second pass: a statement that itself looks like an injection is dropped.
        safe = [
            s.model_dump()
            for s in facts.statements
            if not self.d.scanner.scan(s.statement).is_suspicious
        ]
        return {"facts": safe, "quarantined_lines": quarantined}

    # -- privileged nodes (see only validated facts) ------------------------------------------
    @guarded("retrieve_rules")
    def retrieve_rules(self, state: ComplianceState) -> dict[str, Any]:
        catalog = load_catalog(self.d.catalog_dir, state["doc_type"])
        ctx = SecurityContext(
            state["tenant_id"], tuple(state.get("groups", [])), state.get("actor", "agent")
        )
        rules: list[dict[str, Any]] = []
        for req in catalog.requirements:
            hits = self.d.retrieval.search(
                req.requirement, ctx, MetadataFilter(source=catalog.regulation_source)
            )
            hits.sort(key=lambda h: h.chunk.section_id != req.section)  # stable: section first
            top = hits[:2]
            rules.append(
                {
                    "requirement": req.model_dump(),
                    "citations": [h.chunk.id for h in top],
                    "regulation_text": "\n".join(h.chunk.text[:1500] for h in top),
                }
            )
        return {"rules": rules}

    @staticmethod
    def _relevant_statements(
        req: Requirement, facts: list[dict[str, str]], n: int = 15
    ) -> list[str]:
        """Pre-filter facts per requirement to bound tokens (keyword hits first, then overlap)."""
        req_terms = content_terms(req.requirement)
        kws = [k.lower() for k in req.keywords]

        def score(f: dict[str, str]) -> float:
            s = f["statement"].lower()
            return (2.0 if any(k in s for k in kws) else 0.0) + len(
                req_terms & content_terms(s)
            ) / max(1, len(req_terms))

        ranked = sorted(facts, key=score, reverse=True)
        return [f["statement"] for f in ranked[:n] if score(f) > 0]

    @guarded("compare")
    def compare(self, state: ComplianceState) -> dict[str, Any]:
        comparisons: list[dict[str, Any]] = []
        facts = state.get("facts", [])
        for rule in state.get("rules", []):
            req = Requirement.model_validate(rule["requirement"])
            stmts = self._relevant_statements(req, facts)
            try:
                raw = self._llm(
                    "compare",
                    "compare.v1",
                    state,
                    inputs={"requirement": req.model_dump(), "statements": stmts},
                    requirement_id=req.id,
                    requirement=req.requirement,
                    regulation=wrap_untrusted(rule["regulation_text"], "regulation"),
                    statements=json.dumps(stmts, indent=1),
                )
                comp = parse_structured(raw, Comparison)
            except (LLMError, OutputValidationError) as exc:
                comp = Comparison(
                    status="needs_review", rationale=f"automatic comparison failed: {exc}"
                )
            comparisons.append({"requirement_id": req.id, **comp.model_dump()})
        return {"comparisons": comparisons}

    @guarded("draft_findings")
    def draft_findings(self, state: ComplianceState) -> dict[str, Any]:
        rules = {r["requirement"]["id"]: r for r in state.get("rules", [])}
        findings: list[dict[str, Any]] = []
        for i, comp in enumerate(state.get("comparisons", []), start=1):
            rule = rules[comp["requirement_id"]]
            req = Requirement.model_validate(rule["requirement"])
            findings.append(
                Finding(
                    id=f"F-{i:03d}",
                    requirement_id=req.id,
                    requirement=req.requirement,
                    section=req.section,
                    status=comp["status"],
                    severity=req.severity,
                    rationale=comp["rationale"],
                    evidence=comp["evidence"],
                    regulation_citations=rule["citations"],
                ).model_dump()
            )
        return {"findings": findings, "status": "awaiting_review"}

    def human_review(self, state: ComplianceState) -> dict[str, Any]:
        """Pause for a human. Resumed by ``Command(resume=ReviewDecision)`` via the API."""
        gaps = [f for f in state.get("findings", []) if f["status"] != "compliant"]
        payload = interrupt(
            {
                "check_id": state.get("check_id"),
                "kind": "review_findings",
                "findings": len(state.get("findings", [])),
                "open_items": len(gaps),
            }
        )
        decision = ReviewDecision.model_validate(payload)
        return {"review": decision.model_dump(), "steps": state.get("steps", 0) + 1}

    @guarded("finalize_report")
    def finalize_report(self, state: ComplianceState) -> dict[str, Any]:
        errors = state.get("errors", [])
        review = ReviewDecision.model_validate(state["review"]) if state.get("review") else None
        findings = [Finding.model_validate(f) for f in state.get("findings", [])]
        if review and review.decision == "correct":
            fixes = {c.finding_id: c for c in review.corrections}
            findings = [
                f.model_copy(
                    update={"status": fixes[f.id].status, "reviewer_note": fixes[f.id].note}
                )
                if f.id in fixes
                else f
                for f in findings
            ]
        status = (
            "failed"
            if errors
            else ("rejected" if review and review.decision == "reject" else "completed")
        )
        summary: dict[str, int] = {}
        for f in findings:
            summary[f.status] = summary.get(f.status, 0) + 1
        tickets: list[str] = []
        if self.d.ticketing is not None and status == "completed":
            for f in findings:
                if f.status == "gap" and f.severity == "high":
                    tickets.append(
                        self.d.ticketing.create_ticket(
                            title=f"{f.requirement_id}: compliance gap",
                            body=f.rationale,
                            tenant_id=state["tenant_id"],
                        )
                    )
        report = {
            "check_id": state.get("check_id", ""),
            "document_id": state.get("document_id", ""),
            "doc_type": state.get("doc_type", "unknown"),
            "status": status,
            "findings": [f.model_dump() for f in findings],
            "summary": summary,
            "reviewed_by": review.reviewer if review else None,
            "quarantined_lines": len(state.get("quarantined_lines", [])),
            "errors": errors,
            "tickets": tickets,
        }
        metrics.CHECKS.labels(status).inc()
        return {"report": report, "status": status}
