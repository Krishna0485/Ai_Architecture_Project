# Resume bullets and interview prep (from the measured results)

All numbers below come from `regintel/evals/reports/summary.json` and
`regintel/benchmarks/results/latest.md` (2026-11-07). They were measured in **lite mode**:
offline deterministic provider, hashing embedder, 71-question golden set. Quote them that way.
Re-run in full mode (Ollama) before quoting model-quality numbers.

## Projects section (resume)

**RegIntel: Agentic Compliance Intelligence Platform** · github.com/Krishna0485/Ai_Architecture_Project
- Built hybrid retrieval (BM25 + dense vectors, Reciprocal Rank Fusion, reranking) over US
  federal regulations. MRR rose from 0.79 to 0.92 and context precision from 0.76 to 0.90 against a
  vector-only baseline, on a 71-question golden set validated against the source text.
- Designed a LangGraph multi-agent compliance check with a quarantine trust boundary and
  human-in-the-loop review (Postgres checkpoints). It found 9/9 planted gaps with no false
  positives across 7 synthetic policies, with identical findings under prompt injection.
- Cut tokens per request by 39% with context compression, and estimated cost per 1K requests from
  $12.48 to $1.32 with routing plus semantic caching (repeat-heavy workload). Built an LLM gateway
  with fallbacks and per-tenant token budgets.
- Shipped it production-style: an MCP server (stdio + authenticated HTTP), tenant isolation
  enforced in the stores, PII redaction, OpenTelemetry/Prometheus/Grafana, a Helm chart, and CI
  with eval gates. 138 tests at 97% coverage under `mypy --strict`.

Skills to add: Qdrant, OpenSearch, LiteLLM, Ollama, LangGraph, MCP (FastMCP), Langfuse,
OpenTelemetry, Prometheus/Grafana, Helm, Presidio, RAGAS.

## Questions you must be able to answer

**Why hybrid search, and why RRF?** Show ADR-0002's table. RRF fuses ranks, not scores, so BM25's
unbounded scores and cosine similarities need no calibration. Be candid: on this corpus BM25 alone
matched hybrid+rerank (MRR 0.92) because the lite-mode embedder is lexical. Plain hybrid without
reranking was slightly *worse* than BM25. The reranker recovered the gap and gave the best
citation precision. The next experiment is BGE embeddings with paraphrase-heavy questions.

**How did you build and validate the golden set, and how do you avoid overfitting?** Questions were
written per section. Each item carries a verbatim `evidence` phrase that `build_golden.py` checks
against the regulation text; this caught 3 wrong references. `min_score` and the reranker weights
were tuned on the same set, so the numbers are optimistic. The fix is a held-out slice, growing
to 150–300 items, and paraphrase questions written without looking at the text.

**What is faithfulness, and how reliable is LLM-as-judge?** RAGAS faithfulness = share of answer
claims supported by the context. The CI gate uses a lexical proxy, which is ~1.0 by construction
with an extractive generator, so it is not evidence of model quality. For judges: calibrate on
30–50 human labels (Spearman, within-one agreement, bias), use rag-eval-kit's `calibrate`, and
don't let the same model judge its own answers without saying so.

**Walk through the LangGraph state and the review interrupt. What happens on restart?** The
`ComplianceState` TypedDict is checkpointed after every node. `human_review` calls `interrupt()`
and the graph stops. On restart the Postgres checkpointer still holds the thread, so
`POST /review` resumes it with `Command(resume=...)`. The reviewer identity comes from the API
key, not the body (there is a test for a spoofed reviewer).

**How do you stop indirect prompt injection from changing findings?** Use the quarantine pattern
(ADR-0005). Only tool-less nodes read uploads. Their output is schema-validated facts.
Suspicious lines are removed, and statements are re-scanned. Requirements come from the
catalogue, not the document. Malformed output becomes `needs_review`. Tests show identical
findings with and without the injection, and that injected text never reaches the compare
prompts even with a compromised extractor.

**How is tenant isolation enforced and tested?** Filters run inside the stores (in-memory scan,
Qdrant payload filter, OpenSearch bool filter), built from the `SecurityContext` derived from the
key. Documents, checks and audit logs are tenant-scoped and return 404 rather than 403. Tests
probe every retrieval configuration with canary strings. Known limitation: BM25 IDF statistics
are global.

**What did quantisation cost you in accuracy?** Not measured yet, so say so. The benchmark and
LiteLLM aliases for q4/q8/fp16 are ready. The method is to run `make bench --quant-models` plus
`make eval` per level, then pick the lowest precision within the regression limits.

**How does routing decide, and what are the fallbacks?** Routing is by task: narrow tasks
(rewrite, classify, extract, checklist) go to `fast`, reasoning tasks to `smart`. Fallbacks
happen in two layers: LiteLLM `smart → smart-hosted`, and the gateway's provider chain. An
offline provider is the last resort. Budgets are checked before every call.

**100 tenants and 1M documents: what changes?** Qdrant with sharding and payload indexes, or
per-tenant collections for large tenants. OpenSearch instead of in-process BM25 (and per-tenant
statistics). Ingestion workers with incremental re-indexing by content hash. The semantic cache
on a Redis vector index instead of a linear scan. Queue-mode checks with parallel per-requirement
comparison. Per-tenant cost dashboards and rate limits. A golden set per regulation family.

**Known limitations?** Lite-mode numbers aren't model quality. The golden set is small and was
used for tuning. Abstention misses an unseen-entity case (Globex). Regex PII has no NER without
Presidio. The heuristic injection scanner can be bypassed (the architecture is the real control).
A tenant can lie in its own document; that's for human review.
