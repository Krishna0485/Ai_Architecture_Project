# ADR-0004: LLM gateway, model routing and local-first models

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
Requirements: run fully local (privacy, zero marginal cost) but allow a stronger hosted model;
control spend per tenant; switch models without code changes; measure tokens and cost.

## Options considered
1. Call provider SDKs directly - fastest to start, vendor lock-in, no central budgets/caching.
2. **In-process gateway + LiteLLM proxy** - one `LLMGateway` class owns routing, budgets, exact
   cache, fallbacks, metrics; LiteLLM maps aliases (`fast`, `smart`) to Ollama or hosted models.
3. A managed AI gateway product - good features, extra vendor and cost.

## Decision
Option 2. Code asks for a *task*; `RoutingPolicy` maps narrow tasks (rewrite, classify, extract,
checklist) to `fast` and reasoning tasks (answer, compare, testgen, judge) to `smart`. LiteLLM
(`infra/litellm.yaml`) serves `fast` = qwen2.5 3B q4 and `smart` = qwen2.5 7B q4 on Ollama, with a
hosted fallback for `smart`. The gateway adds a client-side fallback chain, per-request and
per-tenant-per-day token budgets, an exact-match response cache, and cost estimation.

## Evidence
`benchmarks/results/latest.md` (2026-11-07, 300 requests, offline provider, pricing assumption
smart = $3/$15 per 1M tokens, fast = local $0): routing lowered estimated cost from $8.16 to
$7.53 per 1K requests at equal tokens; compression cut tokens/request from 3730 to 2282; the
semantic cache brought cost to $1.32 per 1K on a repeat-heavy workload (cache rows vary by a few percent between runs: concurrent requests can miss simultaneously).

## Consequences
- Positive: model choice is configuration; every call is metered; offline mode for CI.
- Negative: two hops (gateway + proxy); cost figures are estimates from a pricing table.
- Follow-ups: quantisation comparison (q4/q8/fp16) on real hardware with
  `run_bench.py --quant-models`; route by measured difficulty, not only by task.

## How we will know it was right
Per-tenant cost dashboards stay within budget; eval metrics with the `fast` route stay within
regression limits of the all-`smart` baseline.
