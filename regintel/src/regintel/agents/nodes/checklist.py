"""Nodes of the ``checklist_and_testgen`` graph."""

from __future__ import annotations

import ast
import json
from typing import Any

from regintel.agents.deps import AgentDeps
from regintel.agents.models import Checklist, TestScenario, TestSuite
from regintel.agents.state import ChecklistState
from regintel.guardrails import OutputValidationError, parse_structured, wrap_untrusted
from regintel.llm.base import LLMError, LLMRequest
from regintel.retrieval.base import SecurityContext


class ChecklistNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.d = deps

    def _llm(
        self,
        task: str,
        prompt_id: str,
        state: ChecklistState,
        inputs: dict[str, Any],
        **variables: object,
    ) -> str:
        system, user = self.d.prompts.render(prompt_id, **variables)
        return self.d.gateway.complete(
            LLMRequest(
                task=task,
                prompt_id=prompt_id,
                system=system,
                user=user,
                inputs=inputs,
                json_mode=True,
                max_tokens=2000,
                tenant_id=state.get("tenant_id", "public"),
            )
        ).text

    def load_section(self, state: ChecklistState) -> dict[str, Any]:
        ctx = SecurityContext(state["tenant_id"], tuple(state.get("groups", [])))
        chunks = [
            c
            for c in self.d.chunks.by_section(state["section_id"], state.get("source") or None)
            if ctx.can_see(c)
        ]
        if not chunks:
            return {"errors": [f"section {state['section_id']} not found"]}
        body = "\n".join(c.text.split("\n", 1)[-1] for c in chunks)
        return {
            "section_text": f"{chunks[0].text.split(chr(10), 1)[0]}\n{body}",
            "source": chunks[0].metadata.get("source", ""),
            "citations": [c.id for c in chunks],
        }

    def generate_checklist(self, state: ChecklistState) -> dict[str, Any]:
        if state.get("errors"):
            return {}
        try:
            raw = self._llm(
                "checklist",
                "checklist.v1",
                state,
                {"section_id": state["section_id"], "section_text": state["section_text"]},
                section_id=state["section_id"],
                section_text=wrap_untrusted(state["section_text"], "regulation"),
            )
            checklist = parse_structured(raw, Checklist)
        except (LLMError, OutputValidationError) as exc:
            return {"errors": [f"checklist: {exc}"]}
        return {"checklist": [i.model_dump() for i in checklist.items]}

    def generate_tests(self, state: ChecklistState) -> dict[str, Any]:
        if state.get("errors") or not state.get("checklist"):
            return {}
        try:
            raw = self._llm(
                "testgen",
                "testgen.v1",
                state,
                {"items": state["checklist"]},
                items=json.dumps(state["checklist"], indent=1),
            )
            suite = parse_structured(raw, TestSuite)
        except (LLMError, OutputValidationError) as exc:
            return {"errors": [f"testgen: {exc}"]}
        return {"tests": [t.model_dump() for t in suite.tests]}

    def validate(self, state: ChecklistState) -> dict[str, Any]:
        """Generated pytest code must parse and define exactly one ``test_*`` function; it is
        never executed here."""
        valid: list[dict[str, Any]] = []
        errors = list(state.get("errors", []))
        known = {i["id"] for i in state.get("checklist", [])}
        for t in state.get("tests", []):
            scenario = TestScenario.model_validate(t)
            if scenario.item_id not in known:
                errors.append(f"test for unknown item {scenario.item_id}")
                continue
            try:
                tree = ast.parse(scenario.pytest)
            except SyntaxError as exc:
                errors.append(f"{scenario.item_id}: invalid pytest code ({exc.msg})")
                continue
            funcs = [
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
            ]
            if len(funcs) != 1 or len(tree.body) != 1:
                errors.append(f"{scenario.item_id}: expected exactly one test function")
                continue
            valid.append(scenario.model_dump())
        return {"tests": valid, "errors": errors}
