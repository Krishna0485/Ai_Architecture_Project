"""The LLM gateway: the only path to any model.

Responsibilities: routing (task -> model alias), token budgets, exact-match response cache,
provider fallbacks, timeouts (provider level), cost estimation, metrics, tracing.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterator

from regintel.cache.base import KeyValueCache
from regintel.config import Settings
from regintel.llm.base import LLMError, LLMProvider, LLMRequest, LLMResponse
from regintel.llm.budget import TokenBudget
from regintel.llm.routing import RoutingPolicy
from regintel.observability import metrics
from regintel.observability.langfuse import GenerationTracer, NoopTracer
from regintel.observability.tracing import span
from regintel.text import count_tokens

log = logging.getLogger(__name__)


class LLMGateway:
    def __init__(
        self,
        providers: list[tuple[LLMProvider, str | None]],
        routing: RoutingPolicy,
        budget: TokenBudget,
        pricing: dict[str, tuple[float, float]],
        cache: KeyValueCache | None = None,
        tracer: GenerationTracer | None = None,
    ) -> None:
        """``providers`` is an ordered fallback chain of (provider, model_override). A ``None``
        override means "use the routed alias"; an explicit model pins that provider's model."""
        if not providers:
            raise ValueError("at least one provider required")
        self.providers = providers
        self.routing = routing
        self.budget = budget
        self.pricing = pricing
        self.cache = cache
        self.tracer = tracer or NoopTracer()

    def _cost(self, alias: str, prompt_tokens: int, completion_tokens: int) -> float:
        p_in, p_out = self.pricing.get(alias, (0.0, 0.0))
        return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000

    @staticmethod
    def _cache_key(req: LLMRequest, model: str) -> str:
        raw = "\x1f".join([req.tenant_id, req.prompt_id, model, req.system, req.user])
        return "llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def complete(self, req: LLMRequest) -> LLMResponse:
        model = self.routing.model_for(req.task, req.model)
        alias = self.routing.alias_of(model)
        prompt_tokens = count_tokens(req.system + req.user)
        self.budget.check(req.tenant_id, prompt_tokens, req.max_tokens)

        key = self._cache_key(req, model)
        if self.cache is not None and req.cacheable and req.temperature == 0:
            hit = self.cache.get(key)
            metrics.CACHE_EVENTS.labels("llm_exact", "hit" if hit else "miss").inc()
            if hit is not None:
                cached = LLMResponse.model_validate_json(hit)
                return cached.model_copy(
                    update={"cached": True, "latency_ms": 0.0, "cost_usd": 0.0}
                )

        errors: list[str] = []
        with span("llm.complete", task=req.task, model=model, prompt_id=req.prompt_id) as s:
            for i, (provider, override) in enumerate(self.providers):
                target = override or model
                start = time.perf_counter()
                try:
                    resp = provider.complete(req, target)
                except LLMError as exc:
                    errors.append(str(exc))
                    metrics.LLM_FALLBACKS.labels(req.task).inc()
                    log.warning("provider %s failed (%s); trying next", provider.name, exc)
                    continue
                elapsed = time.perf_counter() - start
                cost_alias = alias if override is None else override
                resp = resp.model_copy(
                    update={
                        "latency_ms": elapsed * 1000,
                        "cost_usd": self._cost(
                            cost_alias, resp.usage.prompt_tokens, resp.usage.completion_tokens
                        ),
                    }
                )
                self._record(req, resp, alias, elapsed)
                s.set_attribute("regintel.provider_index", i)
                s.set_attribute("regintel.tokens", resp.usage.total)
                if self.cache is not None and req.cacheable and req.temperature == 0:
                    self.cache.set(key, resp.model_dump_json())
                return resp
        raise LLMError("all providers failed: " + " | ".join(errors))

    def stream(self, req: LLMRequest) -> Iterator[str]:
        """Stream from the first healthy provider (no cache; fallback only before 1st token)."""
        model = self.routing.model_for(req.task, req.model)
        self.budget.check(req.tenant_id, count_tokens(req.system + req.user), req.max_tokens)
        errors: list[str] = []
        for provider, override in self.providers:
            try:
                produced: list[str] = []
                for token in provider.stream(req, override or model):
                    produced.append(token)
                    yield token
                completion = count_tokens("".join(produced))
                self.budget.record(req.tenant_id, count_tokens(req.user) + completion)
                return
            except LLMError as exc:
                if produced:
                    raise
                errors.append(str(exc))
                metrics.LLM_FALLBACKS.labels(req.task).inc()
        raise LLMError("all providers failed: " + " | ".join(errors))

    def _record(self, req: LLMRequest, resp: LLMResponse, alias: str, elapsed: float) -> None:
        self.budget.record(req.tenant_id, resp.usage.total)
        metrics.LLM_LATENCY.labels(req.task, alias).observe(elapsed)
        metrics.LLM_TOKENS.labels(req.task, alias, "prompt").inc(resp.usage.prompt_tokens)
        metrics.LLM_TOKENS.labels(req.task, alias, "completion").inc(resp.usage.completion_tokens)
        metrics.LLM_COST.labels(alias).inc(resp.cost_usd)
        self.tracer.record(
            name=req.prompt_id,
            model=resp.model,
            input_text=req.user,
            output_text=resp.text,
            usage={"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens},
            metadata={"task": req.task, "tenant": req.tenant_id},
        )


def build_gateway(settings: Settings, cache: KeyValueCache | None = None) -> LLMGateway:
    """Construct the gateway from settings: primary provider + configured fallbacks."""
    from regintel.llm.heuristic import HeuristicProvider
    from regintel.llm.providers import OpenAICompatibleProvider
    from regintel.observability.langfuse import build_tracer

    chain: list[tuple[LLMProvider, str | None]] = []
    if settings.llm_provider == "openai_compatible":
        key = settings.gateway_api_key.get_secret_value() if settings.gateway_api_key else None
        chain.append(
            (OpenAICompatibleProvider(settings.gateway_url, key, settings.llm_timeout_s), None)
        )
        for fb in settings.model_fallbacks:
            if fb == "heuristic":
                chain.append((HeuristicProvider(), "heuristic"))
    else:
        chain.append((HeuristicProvider(), None))
    routing = RoutingPolicy(settings.model_fast, settings.model_smart, settings.routing_enabled)
    budget = TokenBudget(settings.request_token_budget, settings.tenant_daily_token_budget)
    return LLMGateway(chain, routing, budget, settings.pricing, cache, build_tracer(settings))
