"""Typed LangGraph state. Everything in state is JSON-serialisable so it can be checkpointed."""

from __future__ import annotations

from typing import Any, TypedDict


class ComplianceState(TypedDict, total=False):
    # inputs (set once at start; tenant/groups come from the authenticated SecurityContext)
    check_id: str
    document_id: str
    tenant_id: str
    groups: list[str]
    actor: str
    document_text: str  # untrusted; only classify/extract (tool-less, quarantined) read it
    # produced by nodes
    doc_type: str
    classification_confidence: float
    facts: list[dict[str, str]]  # validated DocumentFacts.statements
    quarantined_lines: list[str]
    rules: list[dict[str, Any]]  # requirement + regulation citations/text
    comparisons: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    review: dict[str, Any]
    report: dict[str, Any]
    status: str
    steps: int
    errors: list[str]


class ChecklistState(TypedDict, total=False):
    section_id: str
    source: str
    tenant_id: str
    groups: list[str]
    section_text: str
    citations: list[str]
    checklist: list[dict[str, Any]]
    tests: list[dict[str, Any]]
    errors: list[str]
