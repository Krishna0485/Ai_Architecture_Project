"""Structured (Pydantic) outputs used at every LLM boundary in the agent graphs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

DocType = Literal["information_security_policy", "leave_policy", "credit_policy", "unknown"]
Status = Literal["compliant", "gap", "partial", "needs_review"]
Severity = Literal["high", "medium", "low"]


class Constraint(BaseModel):
    op: Literal["max", "min"]
    value: float
    unit: str


class Requirement(BaseModel):
    id: str
    section: str
    requirement: str
    keywords: list[str] = Field(default_factory=list)
    constraint: Constraint | None = None
    prohibited_pattern: str | None = None
    severity: Severity = "medium"


class Classification(BaseModel):
    doc_type: DocType
    confidence: float = Field(ge=0, le=1)


class Statement(BaseModel):
    topic: str = Field(max_length=200)
    statement: str = Field(max_length=500)


class DocumentFacts(BaseModel):
    """Output of the quarantined extractor: the ONLY view privileged nodes get of a document."""

    statements: list[Statement] = Field(default_factory=list, max_length=200)


class Comparison(BaseModel):
    status: Status
    evidence: list[str] = Field(default_factory=list, max_length=5)
    rationale: str = Field(default="", max_length=1000)

    @field_validator("evidence")
    @classmethod
    def _trim(cls, v: list[str]) -> list[str]:
        return [e[:500] for e in v]


class Finding(BaseModel):
    id: str
    requirement_id: str
    requirement: str
    section: str
    status: Status
    severity: Severity
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    regulation_citations: list[str] = Field(default_factory=list)
    reviewer_note: str | None = None


class FindingCorrection(BaseModel):
    finding_id: str
    status: Status
    note: str = Field(default="", max_length=1000)


class ReviewDecision(BaseModel):
    decision: Literal["approve", "correct", "reject"]
    reviewer: str = "reviewer"
    corrections: list[FindingCorrection] = Field(default_factory=list)
    comment: str = Field(default="", max_length=2000)


class ComplianceReport(BaseModel):
    check_id: str
    document_id: str
    doc_type: str
    status: Literal["completed", "rejected", "failed"]
    findings: list[Finding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    reviewed_by: str | None = None
    quarantined_lines: int = 0
    errors: list[str] = Field(default_factory=list)
    tickets: list[str] = Field(default_factory=list)


class ChecklistItem(BaseModel):
    id: str
    requirement: str = Field(max_length=600)
    evidence_needed: str = Field(default="", max_length=600)


class Checklist(BaseModel):
    section_id: str
    items: list[ChecklistItem] = Field(default_factory=list, max_length=20)


class TestScenario(BaseModel):
    item_id: str
    pytest: str
    gherkin: str


class TestSuite(BaseModel):
    tests: list[TestScenario] = Field(default_factory=list)


class ChecklistResult(BaseModel):
    section_id: str
    source: str = ""
    citations: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    tests: list[TestScenario] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
