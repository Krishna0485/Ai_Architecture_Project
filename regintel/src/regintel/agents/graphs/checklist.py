"""checklist_and_testgen graph: section -> checklist -> pytest/BDD scenarios -> validation."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from regintel.agents.nodes.checklist import ChecklistNodes
from regintel.agents.state import ChecklistState


def build_checklist_graph(nodes: ChecklistNodes) -> Any:
    g: StateGraph[ChecklistState] = StateGraph(ChecklistState)
    g.add_node("load_section", nodes.load_section)
    g.add_node("generate_checklist", nodes.generate_checklist)
    g.add_node("generate_tests", nodes.generate_tests)
    g.add_node("validate", nodes.validate)
    g.add_edge(START, "load_section")
    g.add_edge("load_section", "generate_checklist")
    g.add_edge("generate_checklist", "generate_tests")
    g.add_edge("generate_tests", "validate")
    g.add_edge("validate", END)
    return g.compile()
