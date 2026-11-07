"""compliance_check graph.

    classify_document -> extract_obligations -> retrieve_rules -> compare -> draft_findings
        -> human_review (interrupt) -> finalize_report -> END

Any node error short-circuits to finalize_report (status=failed). Unsupported document types
also go straight to finalize_report.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from regintel.agents.nodes.compliance import ComplianceNodes
from regintel.agents.state import ComplianceState

MERMAID = """flowchart TD
    start([start]) --> classify_document
    classify_document -->|supported type| extract_obligations
    classify_document -->|unknown / error| finalize_report
    extract_obligations --> retrieve_rules
    retrieve_rules --> compare
    compare --> draft_findings
    draft_findings --> human_review{{human_review - interrupt}}
    human_review --> finalize_report
    finalize_report --> done([end])
"""


def _next_or_finalize(nxt: str) -> Callable[[ComplianceState], str]:
    def route(state: ComplianceState) -> str:
        return "finalize_report" if state.get("errors") else nxt

    return route


def _after_classify(state: ComplianceState) -> str:
    if state.get("errors"):
        return "finalize_report"
    if state.get("doc_type", "unknown") == "unknown":
        return "finalize_report"
    return "extract_obligations"


def build_compliance_graph(nodes: ComplianceNodes, checkpointer: Any) -> Any:
    g: StateGraph[ComplianceState] = StateGraph(ComplianceState)
    # Bound methods are typed loosely: LangGraph's node protocols are invariant in the state type.
    steps: dict[str, Any] = {
        "classify_document": nodes.classify_document,
        "extract_obligations": nodes.extract_obligations,
        "retrieve_rules": nodes.retrieve_rules,
        "compare": nodes.compare,
        "draft_findings": nodes.draft_findings,
        "human_review": nodes.human_review,
        "finalize_report": nodes.finalize_report,
    }
    for name, fn in steps.items():
        g.add_node(name, fn)

    g.add_edge(START, "classify_document")
    g.add_conditional_edges(
        "classify_document", _after_classify, ["extract_obligations", "finalize_report"]
    )
    for src, dst in (
        ("extract_obligations", "retrieve_rules"),
        ("retrieve_rules", "compare"),
        ("compare", "draft_findings"),
        ("draft_findings", "human_review"),
    ):
        g.add_conditional_edges(src, _next_or_finalize(dst), [dst, "finalize_report"])
    g.add_edge("human_review", "finalize_report")
    g.add_edge("finalize_report", END)
    return g.compile(checkpointer=checkpointer)
