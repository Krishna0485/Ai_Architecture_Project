"""Model routing policy: cheap/fast local model for narrow tasks, larger model for reasoning."""

from __future__ import annotations

from dataclasses import dataclass, field

FAST_TASKS = frozenset({"query_rewrite", "classify_document", "extract_facts", "checklist"})
SMART_TASKS = frozenset({"answer", "compare", "testgen", "judge"})


@dataclass
class RoutingPolicy:
    fast_model: str = "fast"
    smart_model: str = "smart"
    enabled: bool = True
    overrides: dict[str, str] = field(default_factory=dict)

    def model_for(self, task: str, explicit: str | None = None) -> str:
        """Return the model alias for a task. Explicit request alias > override > policy."""
        if explicit:
            return {"fast": self.fast_model, "smart": self.smart_model}.get(explicit, explicit)
        if task in self.overrides:
            return self.overrides[task]
        if not self.enabled:
            return self.smart_model  # single-model baseline used in benchmarks
        return self.fast_model if task in FAST_TASKS else self.smart_model

    def alias_of(self, model: str) -> str:
        if model == self.fast_model:
            return "fast"
        if model == self.smart_model:
            return "smart"
        return model
