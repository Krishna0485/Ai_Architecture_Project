"""Dependencies shared by agent nodes (injected, so nodes are unit-testable with fakes)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from regintel.generation.prompts import PromptRegistry
from regintel.guardrails import InjectionScanner, PIIRedactor
from regintel.llm.gateway import LLMGateway
from regintel.retrieval.factory import RetrievalPipeline
from regintel.storage.index_store import ChunkStore


@dataclass
class AgentDeps:
    gateway: LLMGateway
    prompts: PromptRegistry
    retrieval: RetrievalPipeline
    chunks: ChunkStore
    scanner: InjectionScanner
    redactor: PIIRedactor
    catalog_dir: Path
    max_steps: int = 40
    ticketing: Any | None = None  # optional MCP ticketing client (see agents/mcp_client.py)
