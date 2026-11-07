from __future__ import annotations

import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from regintel.agents.catalog import available_doc_types, load_catalog
from regintel.agents.deps import AgentDeps
from regintel.agents.graphs.compliance_check import MERMAID, build_compliance_graph
from regintel.agents.models import FindingCorrection, ReviewDecision
from regintel.agents.nodes.checklist import ChecklistNodes
from regintel.agents.nodes.compliance import ComplianceNodes
from regintel.agents.service import (
    AgentsDisabledError,
    CheckConflictError,
    CheckNotFoundError,
    CheckService,
)
from regintel.agents.tools import ToolError
from regintel.audit.writer import InMemoryAuditWriter
from regintel.container import Container
from regintel.guardrails import PolicyDeniedError
from regintel.llm.base import LLMRequest
from regintel.llm.budget import TokenBudget
from regintel.llm.gateway import LLMGateway
from regintel.llm.heuristic import HeuristicProvider
from regintel.llm.routing import RoutingPolicy
from regintel.retrieval.base import SecurityContext
from regintel.storage.documents import DocumentRepository
from tests.conftest import synthetic
from tests.fixtures.fakes import ScriptedProvider

CTX = SecurityContext("acme", ("compliance",), "alice")


def deps_with(container: Container, fn: Any, max_steps: int = 40) -> AgentDeps:
    gw = LLMGateway([(ScriptedProvider(fn), None)], RoutingPolicy(), TokenBudget(10**6, 10**9), {})
    return AgentDeps(
        gw,
        container.prompts,
        container.retrieval,
        container.chunks,
        container.scanner,
        container.redactor,
        container.settings.catalog_dir,
        max_steps,
    )


def heuristic(r: LLMRequest) -> str:
    return HeuristicProvider().complete(r, "x").text


def base_state(text: str) -> dict[str, Any]:
    return {
        "check_id": "chk_1",
        "document_id": "doc_1",
        "tenant_id": "acme",
        "groups": ["compliance"],
        "actor": "alice",
        "document_text": text,
        "steps": 0,
        "errors": [],
    }


def test_catalogs_load() -> None:
    from regintel.config import Settings

    d = Settings().catalog_dir
    assert available_doc_types(d) == [
        "credit_policy",
        "information_security_policy",
        "leave_policy",
    ]
    cat = load_catalog(d, "information_security_policy")
    assert cat.regulation_source == "16cfr314" and len(cat.requirements) == 14
    with pytest.raises(FileNotFoundError):
        load_catalog(d, "nope")


def test_classify_and_extract_nodes(container: Container) -> None:
    nodes = ComplianceNodes(deps_with(container, heuristic))
    state = base_state(synthetic("acme_infosec_policy_injected.md"))
    out = nodes.classify_document(state)  # type: ignore[arg-type]
    assert out["doc_type"] == "information_security_policy" and out["steps"] == 1
    out = nodes.extract_obligations(state)  # type: ignore[arg-type]
    assert out["quarantined_lines"] and all(
        "ignore" not in f["statement"].lower() for f in out["facts"]
    )


def test_retrieve_rules_cites_requirement_section(container: Container) -> None:
    nodes = ComplianceNodes(deps_with(container, heuristic))
    out = nodes.retrieve_rules({**base_state(""), "doc_type": "leave_policy"})  # type: ignore[typeddict-item]
    by_id = {r["requirement"]["id"]: r for r in out["rules"]}
    assert by_id["FMLA-ELIGIBILITY-HOURS"]["citations"][0].startswith("29cfr825:825.110")
    assert all(c.startswith("29cfr825:") for r in out["rules"] for c in r["citations"])


def test_compare_marks_malformed_model_output_for_review(container: Container) -> None:
    nodes = ComplianceNodes(deps_with(container, lambda r: "not json"))
    rules = ComplianceNodes(deps_with(container, heuristic)).retrieve_rules(
        {**base_state(""), "doc_type": "credit_policy"}
    )["rules"]  # type: ignore[typeddict-item]
    out = nodes.compare({**base_state(""), "rules": rules, "facts": []})  # type: ignore[typeddict-item]
    assert {c["status"] for c in out["comparisons"]} == {"needs_review"}


def test_node_errors_become_state_errors_and_step_limit(container: Container) -> None:
    nodes = ComplianceNodes(deps_with(container, lambda r: "garbage"))
    out = nodes.classify_document(base_state("text"))  # type: ignore[arg-type]
    assert out["errors"] and "classify_document" in out["errors"][0]
    limited = ComplianceNodes(deps_with(container, heuristic, max_steps=1))
    out = limited.classify_document({**base_state("x"), "steps": 1})  # type: ignore[typeddict-item]
    assert "step limit" in out["errors"][0]


def run_graph(container: Container, fn: Any, text: str) -> tuple[Any, dict[str, Any]]:
    graph = build_compliance_graph(ComplianceNodes(deps_with(container, fn)), MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    graph.invoke(base_state(text), cfg)
    return graph, cfg


def test_graph_interrupts_for_review_then_applies_corrections(container: Container) -> None:
    graph, cfg = run_graph(container, heuristic, synthetic("acme_leave_policy_gaps.md"))
    snap = graph.get_state(cfg)
    assert snap.next == ("human_review",)
    findings = snap.values["findings"]
    target = next(f for f in findings if f["status"] == "gap")
    from langgraph.types import Command

    decision = ReviewDecision(
        decision="correct",
        reviewer="bob",
        corrections=[
            FindingCorrection(finding_id=target["id"], status="partial", note="accepted risk")
        ],
    )
    graph.invoke(Command(resume=decision.model_dump()), cfg)
    report = graph.get_state(cfg).values["report"]
    fixed = next(f for f in report["findings"] if f["id"] == target["id"])
    assert report["status"] == "completed" and fixed["status"] == "partial"
    assert fixed["reviewer_note"] == "accepted risk" and report["summary"]["gap"] == 2


def test_graph_unknown_document_skips_to_report(container: Container) -> None:
    graph, cfg = run_graph(container, heuristic, "Lunch menu: soup and bread on Fridays.")
    values = graph.get_state(cfg).values
    assert values["status"] == "completed" and values["report"]["doc_type"] == "unknown"
    assert values["report"]["findings"] == []
    assert "human_review" in MERMAID


def test_graph_failure_path(container: Container) -> None:
    graph, cfg = run_graph(container, lambda r: "garbage", "anything")
    assert graph.get_state(cfg).values["report"]["status"] == "failed"


def test_checklist_nodes_validate_generated_code(container: Container) -> None:
    def fn(r: LLMRequest) -> str:
        if r.task == "testgen":
            return json.dumps(
                {
                    "tests": [
                        {
                            "item_id": "314.4-1",
                            "pytest": "def test_ok(policy_text):\n    assert True\n",
                            "gherkin": "Scenario: x",
                        },
                        {"item_id": "314.4-2", "pytest": "def broken(:", "gherkin": "g"},
                        {
                            "item_id": "314.4-3",
                            "pytest": "import os\ndef test_x(): pass",
                            "gherkin": "g",
                        },
                        {"item_id": "zzz", "pytest": "def test_y(): pass", "gherkin": "g"},
                    ]
                }
            )
        return heuristic(r)

    nodes = ChecklistNodes(deps_with(container, fn))
    state: dict[str, Any] = {
        "section_id": "314.4",
        "tenant_id": "acme",
        "groups": ["compliance"],
        "errors": [],
    }
    state |= nodes.load_section(state)  # type: ignore[arg-type]
    assert state["source"] == "16cfr314" and state["citations"]
    state |= nodes.generate_checklist(state)  # type: ignore[arg-type]
    state |= nodes.generate_tests(state)  # type: ignore[arg-type]
    out = nodes.validate(state)  # type: ignore[arg-type]
    assert [t["item_id"] for t in out["tests"]] == ["314.4-1"]
    assert len(out["errors"]) == 3
    missing = nodes.load_section({"section_id": "1.1", "tenant_id": "acme", "groups": []})  # type: ignore[typeddict-item]
    assert missing["errors"]
    assert nodes.generate_checklist({"errors": ["x"]}) == {}  # type: ignore[typeddict-item]


def make_service(container: Container, **kw: Any) -> CheckService:
    return CheckService(
        deps_with(container, heuristic), DocumentRepository(), InMemoryAuditWriter(), **kw
    )


def test_service_lifecycle_and_tenant_isolation(container: Container) -> None:
    svc = make_service(container, executor="background")
    doc = svc.documents.add("acme", "p.md", synthetic("acme_infosec_policy_gaps.md"))
    view = svc.start(doc.id, CTX)
    svc.wait(view.check_id)
    view = svc.get(view.check_id, CTX)
    assert view.status == "awaiting_review" and view.pending_review["open_items"] == 3  # type: ignore[index]
    other = SecurityContext("globex", ("compliance",), "eve")
    with pytest.raises(CheckNotFoundError):
        svc.get(view.check_id, other)
    with pytest.raises(CheckNotFoundError):
        svc.start(doc.id, other)
    with pytest.raises(ValueError, match="unknown finding"):
        svc.review(
            view.check_id,
            ReviewDecision(
                decision="correct",
                corrections=[FindingCorrection(finding_id="F-999", status="gap")],
            ),
            CTX,
        )
    done = svc.review(view.check_id, ReviewDecision(decision="approve", reviewer="spoofed"), CTX)
    assert done.status == "completed" and done.report["reviewed_by"] == "alice"  # type: ignore[index]
    with pytest.raises(CheckConflictError):
        svc.review(view.check_id, ReviewDecision(decision="approve"), CTX)
    actions = [e.action for e in svc.audit.query("acme")]  # type: ignore[attr-defined]
    assert {"check_document", "review_check"} <= set(actions)


def test_service_kill_switch(container: Container) -> None:
    svc = make_service(container, enabled=False)
    with pytest.raises(AgentsDisabledError):
        svc.start("doc_x", CTX)
    with pytest.raises(AgentsDisabledError):
        svc.checklist("314.4", CTX)


def test_tools_validate_authorise_and_audit(container: Container) -> None:
    tools = container.tools
    res = tools.search_regulations(CTX, query="multi-factor authentication", k=3)
    assert len(res["results"]) == 3
    with pytest.raises(ToolError):
        tools.search_regulations(CTX, query="x")
    with pytest.raises(ToolError):
        tools.check_document(CTX, document_id="../../etc/passwd")
    with pytest.raises(PolicyDeniedError):
        tools.check_document(SecurityContext("acme", ("reader",)), document_id="doc_0123456789ab")
    assert tools.ask(CTX, "How many workweeks of FMLA leave?")["citations"]
    cl = tools.get_checklist(CTX, section_id="825.110", source="29cfr825")
    assert cl["checklist"]
    events = container.audit.query("acme")
    assert any(e.action == "tool:check_document" and e.decision == "deny" for e in events)
    assert any(e.action == "tool:search_regulations" and e.decision == "allow" for e in events)
