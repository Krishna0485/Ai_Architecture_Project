"""Single source of configuration (pydantic-settings).

Every setting can be overridden with an environment variable prefixed ``REGINTEL_``
(for example ``REGINTEL_RETRIEVAL_MODE=hybrid``). No other module reads ``os.environ``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ApiKeyGrant(BaseModel):
    """What an API key grants: a tenant and a set of groups. Never derived from user text."""

    tenant_id: str
    groups: list[str] = Field(default_factory=list)
    actor: str = "api-client"


def _default_api_keys() -> dict[str, ApiKeyGrant]:
    # Development-only keys. Production deployments must set REGINTEL_API_KEYS.
    return {
        "dev-key-acme": ApiKeyGrant(
            tenant_id="acme", groups=["compliance", "hr", "admin"], actor="acme-dev"
        ),
        "dev-key-globex": ApiKeyGrant(
            tenant_id="globex", groups=["compliance"], actor="globex-dev"
        ),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REGINTEL_", env_file=".env", extra="ignore", env_nested_delimiter="__"
    )

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    project_root: Path = PROJECT_ROOT
    prompts_dir: Path = PROJECT_ROOT / "prompts"
    data_dir: Path = PROJECT_ROOT / "data"
    index_path: Path = PROJECT_ROOT / "data" / "index" / "chunks.jsonl"
    catalog_dir: Path = PROJECT_ROOT / "data" / "catalog"

    # --- Ingestion / chunking -------------------------------------------------------------
    chunk_min_tokens: int = 300
    chunk_max_tokens: int = 800

    # --- Retrieval ------------------------------------------------------------------------
    embedder: Literal["hashing", "bge"] = "hashing"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 1024
    vector_store: Literal["memory", "qdrant"] = "memory"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "regintel_chunks"
    keyword_store: Literal["bm25", "opensearch"] = "bm25"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "regintel_chunks"
    reranker: Literal["lexical", "cross-encoder"] = "lexical"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    use_rerank: bool = True
    use_query_rewrite: bool = False
    top_k: int = 20
    rerank_top_n: int = 5
    rrf_k: int = 60
    min_score: float = 0.40  # abstain when IDF-weighted query coverage is below this

    # --- Generation / LLM gateway ---------------------------------------------------------
    llm_provider: Literal["heuristic", "openai_compatible"] = "heuristic"
    gateway_url: str = "http://localhost:4000"
    gateway_api_key: SecretStr | None = None
    model_fast: str = "fast"
    model_smart: str = "smart"
    model_fallbacks: list[str] = Field(default_factory=lambda: ["heuristic"])
    routing_enabled: bool = True  # False = single-model baseline (everything -> smart)
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 1
    max_output_tokens: int = 700
    request_token_budget: int = 6000
    tenant_daily_token_budget: int = 2_000_000
    context_token_budget: int = 1800
    use_context_compression: bool = True

    # --- Cache ----------------------------------------------------------------------------
    cache_backend: Literal["none", "memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    cache_similarity_threshold: float = 0.93
    cache_ttl_s: int = 86_400

    # --- Guardrails -----------------------------------------------------------------------
    pii_backend: Literal["regex", "presidio"] = "regex"
    injection_threshold: float = 0.5
    allowed_link_domains: list[str] = Field(
        default_factory=lambda: [
            "ecfr.gov",
            "www.ecfr.gov",
            "dol.gov",
            "www.dol.gov",
            "ftc.gov",
            "www.ftc.gov",
            "consumerfinance.gov",
        ]
    )

    # --- Agents ---------------------------------------------------------------------------
    agents_enabled: bool = True  # kill switch for agent workflows
    agent_max_steps: int = 40
    checkpointer: Literal["memory", "postgres"] = "memory"
    postgres_dsn: SecretStr = SecretStr("postgresql://postgres:devonly@localhost:5432/regintel")
    check_executor: Literal["inline", "background", "queue"] = "background"
    ticketing_mcp_command: str | None = None  # e.g. "python -m servers.ticketing_mock"
    ticketing_mcp_env: dict[str, SecretStr] = Field(default_factory=dict)  # service token etc.

    # --- Security / tenancy ---------------------------------------------------------------
    api_keys: dict[str, ApiKeyGrant] = Field(default_factory=_default_api_keys)
    mcp_default_api_key: SecretStr | None = None  # stdio transport identity
    audit_backend: Literal["jsonl", "memory", "postgres"] = "jsonl"
    audit_path: Path = PROJECT_ROOT / "data" / "audit" / "audit.jsonl"
    documents_path: Path = PROJECT_ROOT / "data" / "uploads"

    # --- Observability --------------------------------------------------------------------
    otel_enabled: bool = False
    otel_endpoint: str | None = None
    service_name: str = "regintel-api"
    langfuse_host: str | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    metrics_enabled: bool = True

    # Pricing used to estimate cost (USD per 1M tokens: input, output) by model alias.
    pricing: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "fast": (0.0, 0.0),  # local quantised model via Ollama
            "smart": (3.0, 15.0),  # hosted frontier model (fallback / smart route)
            "heuristic": (0.0, 0.0),
        }
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
