"""Langfuse LLM tracing (self-hosted, see infra/compose/docker-compose.observability.yml).

No-op unless the ``observability`` extra is installed and keys are configured. Prompts are
recorded *after* PII redaction by the gateway caller; never log raw uploads.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from regintel.config import Settings

log = logging.getLogger(__name__)


class GenerationTracer(Protocol):
    def record(
        self,
        *,
        name: str,
        model: str,
        input_text: str,
        output_text: str,
        usage: dict[str, int],
        metadata: dict[str, Any],
    ) -> None: ...


class NoopTracer:
    def record(
        self,
        *,
        name: str,
        model: str,
        input_text: str,
        output_text: str,
        usage: dict[str, int],
        metadata: dict[str, Any],
    ) -> None:
        return None


class LangfuseTracer:  # pragma: no cover - requires a Langfuse server
    def __init__(self, settings: Settings) -> None:
        from langfuse import Langfuse

        assert settings.langfuse_public_key and settings.langfuse_secret_key  # noqa: S101
        self._client: Any = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
        )

    def record(
        self,
        *,
        name: str,
        model: str,
        input_text: str,
        output_text: str,
        usage: dict[str, int],
        metadata: dict[str, Any],
    ) -> None:
        try:
            self._client.generation(
                name=name,
                model=model,
                input=input_text,
                output=output_text,
                usage=usage,
                metadata=metadata,
            )
        except Exception:
            log.exception("langfuse record failed")


def build_tracer(settings: Settings) -> GenerationTracer:
    if settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key:
        try:  # pragma: no cover
            return LangfuseTracer(settings)
        except ImportError:  # pragma: no cover
            log.warning("langfuse not installed (uv sync --extra observability)")
    return NoopTracer()
