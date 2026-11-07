"""Composition root: builds every service from Settings. The API, MCP server, worker, evals and
benchmarks all construct the system through ``build_container`` so they run identical code."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from regintel.agents.deps import AgentDeps
from regintel.agents.service import CheckService
from regintel.agents.tools import RegIntelTools
from regintel.audit.writer import AuditWriter, build_audit_writer
from regintel.cache.base import InMemoryCache, KeyValueCache, ListBackend
from regintel.cache.semantic import SemanticCache
from regintel.config import Settings, get_settings
from regintel.generation.answer import AnswerService
from regintel.generation.prompts import PromptRegistry
from regintel.guardrails import InjectionScanner, PIIRedactor, PolicyEngine, build_redactor
from regintel.ingestion.chunker import StructureAwareChunker
from regintel.ingestion.pipeline import ingest_directory
from regintel.llm.gateway import LLMGateway, build_gateway
from regintel.retrieval.base import Chunk
from regintel.retrieval.factory import (
    RetrievalConfig,
    RetrievalPipeline,
    build_embedder,
    build_pipeline,
)
from regintel.retrieval.query_rewrite import QueryRewriter
from regintel.storage.documents import DocumentRepository
from regintel.storage.index_store import ChunkStore, load_chunks

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    chunks: ChunkStore
    gateway: LLMGateway
    prompts: PromptRegistry
    retrieval: RetrievalPipeline
    answers: AnswerService
    checks: CheckService
    tools: RegIntelTools
    documents: DocumentRepository
    audit: AuditWriter
    policy: PolicyEngine
    redactor: PIIRedactor
    scanner: InjectionScanner
    semantic_cache: SemanticCache | None


def load_or_ingest(settings: Settings, sample_dir: Path | None = None) -> list[Chunk]:
    """Load the persisted index; if absent, ingest the bundled sample corpus in-process."""
    chunks = load_chunks(settings.index_path)
    if chunks:
        return chunks
    source = sample_dir or settings.data_dir / "samples"
    log.info("index %s empty - ingesting %s", settings.index_path, source)
    return ingest_directory(
        source, StructureAwareChunker(settings.chunk_min_tokens, settings.chunk_max_tokens)
    )


def _caches(settings: Settings) -> tuple[KeyValueCache | None, ListBackend | None]:
    if settings.cache_backend == "redis":  # pragma: no cover - needs redis
        from regintel.cache.base import RedisCache

        r = RedisCache(settings.redis_url, settings.cache_ttl_s)
        return r, r
    if settings.cache_backend == "memory":
        m = InMemoryCache(ttl_s=settings.cache_ttl_s)
        return m, m
    return None, None


def _checkpointer(settings: Settings) -> Any:
    if settings.checkpointer == "postgres":  # pragma: no cover - needs postgres
        from regintel.storage.postgres import postgres_checkpointer

        return postgres_checkpointer(settings.postgres_dsn.get_secret_value())
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def build_container(
    settings: Settings | None = None,
    *,
    chunks: list[Chunk] | None = None,
    retrieval_config: RetrievalConfig | None = None,
    audit: AuditWriter | None = None,
    documents: DocumentRepository | None = None,
) -> Container:
    settings = settings or get_settings()
    chunk_list = chunks if chunks is not None else load_or_ingest(settings)
    redactor = build_redactor(settings.pii_backend)
    scanner = InjectionScanner(settings.injection_threshold)
    kv, lists = _caches(settings)
    gateway = build_gateway(settings, kv)
    prompts = PromptRegistry(settings.prompts_dir)
    embedder = build_embedder(settings)
    retrieval = build_pipeline(
        settings, chunk_list, embedder, QueryRewriter(gateway, prompts), retrieval_config
    )
    semantic = (
        SemanticCache(embedder, lists, settings.cache_similarity_threshold)
        if lists is not None
        else None
    )
    answers = AnswerService(
        retrieval,
        gateway,
        prompts,
        redactor,
        scanner,
        min_score=settings.min_score,
        context_budget=settings.context_token_budget,
        compress=settings.use_context_compression,
        max_output_tokens=settings.max_output_tokens,
        allowed_link_domains=settings.allowed_link_domains,
        semantic_cache=semantic,
        idf=retrieval.term_weight,
    )
    audit = audit or build_audit_writer(settings, redactor)
    documents = documents or DocumentRepository(
        settings.documents_path if settings.env in ("staging", "prod") else None
    )
    store = ChunkStore(chunk_list)
    ticketing = None
    if settings.ticketing_mcp_command:  # pragma: no cover
        from regintel.agents.mcp_client import MCPTicketingClient

        ticketing = MCPTicketingClient(
            settings.ticketing_mcp_command,
            {k: v.get_secret_value() for k, v in settings.ticketing_mcp_env.items()},
        )
    deps = AgentDeps(
        gateway,
        prompts,
        retrieval,
        store,
        scanner,
        redactor,
        settings.catalog_dir,
        settings.agent_max_steps,
        ticketing,
    )
    queue = None
    if settings.check_executor == "queue":  # pragma: no cover - needs redis
        from regintel.worker import RedisCheckQueue

        queue = RedisCheckQueue(settings.redis_url)
    checks = CheckService(
        deps,
        documents,
        audit,
        checkpointer=_checkpointer(settings),
        executor=settings.check_executor,
        enabled=settings.agents_enabled,
        queue=queue,
    )
    policy = PolicyEngine()
    tools = RegIntelTools(answers, checks, policy, audit)
    return Container(
        settings,
        store,
        gateway,
        prompts,
        retrieval,
        answers,
        checks,
        tools,
        documents,
        audit,
        policy,
        redactor,
        scanner,
        semantic,
    )
