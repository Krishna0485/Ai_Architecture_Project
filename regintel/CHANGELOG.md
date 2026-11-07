# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com),
versioning: [SemVer](https://semver.org). Each release's notes include the eval summary
(`evals/reports/comparison.md`).

## [Unreleased]

## [1.0.0] - 2026-11-07
### Added
- Phase 10: README built from generated reports; architecture, evaluation, security, runbook,
  MCP and benchmark docs; ADRs 0001-0008; Streamlit UI.
- Phase 9: OpenTelemetry spans (API -> retrieval -> gateway -> agents), Prometheus metrics,
  Grafana dashboard, Langfuse integration, observability compose overlay; Helm chart (api, mcp,
  worker; HPA, probes, limits, non-root, NetworkPolicy, PDB, ExternalSecret); release workflow;
  Terraform module.
- Phase 8: regex/Presidio PII redaction (Luhn and Verhoeff checks), injection scanner,
  `wrap_untrusted`, output validation, deny-by-default policy engine, quarantine pattern;
  security test suite; promptfoo red-team config; threat model.
- Phase 7: LLM gateway (routing, fallbacks, budgets, exact cache, cost), semantic cache,
  context compression, LiteLLM aliases for Ollama q4/q8/fp16, `benchmarks/run_bench.py`.
- Phase 6: FastMCP server (stdio + streamable HTTP with token verification) and MCP client.
- Phase 5: LangGraph `compliance_check` (human-review interrupt, checkpointer, step limits) and
  `checklist_and_testgen` graphs; check API; requirement catalogs; synthetic policies.
- Phase 4: BM25, RRF hybrid, lexical and cross-encoder rerankers, query rewriting, metadata filters.
- Phase 3: golden set v1.0 with evidence validation, retrieval/generation metrics, RAGAS and
  judge hooks, HTML report, thresholds and CI eval gate.
- Phase 2: vector retrieval with server-side tenant filters, cited answers with abstention,
  `/v1/ask` + SSE streaming, API-key auth, Docker Compose.
- Phase 1: eCFR downloader and sample corpus, eCFR XML / Markdown / Docling parsers,
  structure-aware chunker, ingestion pipeline, Qdrant/OpenSearch adapters.
- Phase 0: repository skeleton, uv/ruff/mypy/pytest, pre-commit, CI, security policy.

### Evaluation (hybrid + rerank, golden_qa v1.0, lite mode)
hit@5 0.98 · MRR 0.92 · context precision 0.90 · citation precision 0.78 · abstention accuracy
0.97 · agent check gap recall 1.00 / precision 1.00.
