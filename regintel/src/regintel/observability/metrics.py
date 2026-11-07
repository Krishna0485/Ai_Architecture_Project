"""Prometheus metrics. Names are stable: the Grafana dashboard in infra/grafana depends on them."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

REQUEST_LATENCY = Histogram(
    "regintel_request_seconds",
    "API request latency",
    ["route", "status"],
    registry=REGISTRY,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
LLM_LATENCY = Histogram(
    "regintel_llm_seconds",
    "LLM call latency",
    ["task", "model"],
    registry=REGISTRY,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
LLM_TOKENS = Counter(
    "regintel_llm_tokens_total", "LLM tokens", ["task", "model", "kind"], registry=REGISTRY
)
LLM_COST = Counter(
    "regintel_llm_cost_usd_total", "Estimated LLM cost", ["model"], registry=REGISTRY
)
LLM_FALLBACKS = Counter(
    "regintel_llm_fallbacks_total", "Provider fallbacks", ["task"], registry=REGISTRY
)
CACHE_EVENTS = Counter(
    "regintel_cache_events_total", "Cache lookups", ["cache", "result"], registry=REGISTRY
)
GUARDRAIL_BLOCKS = Counter(
    "regintel_guardrail_events_total",
    "Guardrail detections/blocks",
    ["guard", "action"],
    registry=REGISTRY,
)
RETRIEVAL_LATENCY = Histogram(
    "regintel_retrieval_seconds",
    "Retrieval pipeline latency",
    ["mode"],
    registry=REGISTRY,
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)
ABSTENTIONS = Counter("regintel_abstentions_total", "Answers abstained", registry=REGISTRY)
CHECKS = Counter("regintel_checks_total", "Compliance checks", ["status"], registry=REGISTRY)


def render_latest() -> bytes:
    return generate_latest(REGISTRY)
