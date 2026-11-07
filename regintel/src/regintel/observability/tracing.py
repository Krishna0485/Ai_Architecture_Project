"""OpenTelemetry setup. One trace spans API -> retrieval -> gateway -> agents.

Spans are always created through the OTel API (cheap no-ops when no SDK provider is set);
``setup_tracing`` installs an SDK provider with an OTLP exporter when enabled.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from regintel.config import Settings

log = logging.getLogger(__name__)
_TRACER = trace.get_tracer("regintel")
_configured = False


def setup_tracing(settings: Settings, exporter: SpanExporter | None = None) -> bool:
    """Install the SDK tracer provider. Returns True when tracing is active."""
    global _configured
    if _configured or not (settings.otel_enabled or exporter is not None):
        return _configured
    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    if exporter is None:
        try:  # pragma: no cover - optional observability extra
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = (
                OTLPSpanExporter(endpoint=settings.otel_endpoint)
                if settings.otel_endpoint
                else OTLPSpanExporter()
            )
        except ImportError:  # pragma: no cover
            log.warning("OTLP exporter not installed (uv sync --extra observability)")
            return False
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    return True


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    with _TRACER.start_as_current_span(name) as s:
        for key, value in attributes.items():
            if value is not None:
                s.set_attribute(
                    f"regintel.{key}",
                    value if isinstance(value, int | float | bool) else str(value),
                )
        yield s


def current_trace_id() -> str:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.trace_id else ""
