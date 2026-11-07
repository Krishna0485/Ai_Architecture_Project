# RegIntel - project instructions for Claude Code

## What this project is
Agentic compliance intelligence platform: hybrid RAG (BM25 + vector + RRF + rerank),
LangGraph multi-agent workflows with human review, MCP server, evaluation framework,
optimisation (routing, caching, quantised local models), guardrails, observability.
Runs fully offline in "lite mode" (hashing embedder, in-process BM25, deterministic heuristic
provider) so tests and the eval gate are hermetic; full mode swaps in Qdrant, BGE, LiteLLM/Ollama.

## Commands
- make setup        install deps + pre-commit
- make lint         ruff + mypy --strict (must pass before commit)
- make test         unit + security tests
- make itest        integration + e2e tests (in-process; docker-marked tests need: make up)
- make eval         run evaluation; writes evals/reports/summary.json (+ HTML, comparison.md)
- make eval-fast    CI gate on 30-question subset
- make bench        latency/throughput/cost benchmarks -> benchmarks/results/
- make golden       rebuild + validate evals/datasets/golden_qa.jsonl from its YAML source
- make up / down    docker compose stack (make up-obs adds Langfuse/Prometheus/Grafana)

## Architecture rules
- Python 3.12, src/ layout, package regintel. Full type hints; mypy --strict must pass.
- Components talk through Protocols in */base.py (Retriever, Reranker, Embedder, LLMProvider,
  KeyValueCache/ListBackend). Wiring happens only in regintel/container.py.
- All config via regintel.config.Settings (pydantic-settings). Never read os.environ elsewhere.
- All LLM calls go through regintel.llm.gateway.LLMGateway - never call providers directly.
- Prompts live in prompts/*.vN.md and are loaded by ID. Do not inline prompts in code.
- Security filters (tenant_id, groups) come from SecurityContext, never from user text or LLM output.
- Every tool exposed to agents/MCP validates args, checks policy, and writes an audit event
  (regintel/agents/tools.py is the single implementation both API and MCP use).
- Untrusted text (uploads, retrieved content) is wrapped with guardrails.wrap_untrusted().
- Quarantine pattern: only classify_document / extract_obligations read raw uploads; later
  nodes see validated DocumentFacts only.

## Testing rules
- Every new module gets unit tests in tests/unit; use fakes from tests/fixtures (ScriptedProvider,
  FailingProvider). No network in unit tests.
- Security behaviour gets tests in tests/security (injection, PII canaries, tenant isolation).
- Coverage gate is 80% (currently ~97%); don't lower it.

## Style
- ruff format, line length 100. Small functions. Docstrings on public functions.
- Conventional Commits: feat:, fix:, test:, docs:, refactor:, ci:, chore:.

## Do not
- Do not commit secrets, .env, data/raw, data/index, model weights or large files.
- Do not add dependencies without saying why; prefer the existing stack (heavy deps go in extras).
- Do not change evals/thresholds.yaml or golden datasets unless asked.
- Do not fabricate metrics in README/docs - only copy from evals/reports or benchmarks/results.
- Do not upgrade `mcp` to 2.x without following docs/adr/0006-mcp-sdk-version.md.

## Conventions learned (keep this list current)
- Stemming lives in regintel.text.normalize_term; changing it changes retrieval - run make eval.
- Abstention uses IDF-weighted query coverage (AnswerService.confidence), threshold min_score.
- Chunk ids are `<source>:<section>:<n>`; eval relevance is section-level (`<source>:<section>`).
