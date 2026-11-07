"""LLM contracts. All LLM calls go through ``regintel.llm.gateway.LLMGateway``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMRequest(BaseModel):
    task: str  # routing key, e.g. "answer", "query_rewrite", "extract_facts"
    prompt_id: str  # e.g. "answer.v1" - part of every cache key
    system: str = ""
    user: str
    # Structured inputs the prompt was rendered from. Hosted/local models only see the rendered
    # prompt; the offline heuristic provider uses these to stay deterministic.
    inputs: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None  # explicit alias override ("fast" / "smart")
    max_tokens: int = 700
    temperature: float = 0.0
    json_mode: bool = False
    tenant_id: str = "public"
    cacheable: bool = True


class LLMResponse(BaseModel):
    text: str
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest, model: str) -> LLMResponse: ...

    def stream(self, request: LLMRequest, model: str) -> Iterator[str]: ...


class LLMError(RuntimeError):
    """Provider failure (timeouts, 5xx, malformed output)."""


class BudgetExceededError(LLMError):
    """Request or tenant token budget exceeded."""
