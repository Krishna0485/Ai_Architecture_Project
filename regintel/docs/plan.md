# Build plan and status

Ten phases, each ending in a tested, documented increment and a release tag. Status reflects the
repository as of v1.0.0; items marked *(you)* need your accounts, hardware or judgement.

| Phase | Goal | Done when | Status |
|---|---|---|---|
| 0 | Foundation | CI green on a typed package; `make setup` works on a clean machine | done |
| 1 | Ingestion | `make ingest` loads the sample corpus; chunker unit tests; ADR-0001 | done |
| 2 | Baseline RAG + API | cited answer via curl/UI; integration test | done |
| 3 | Evaluation | baseline numbers in `evals/reports/summary.json`; CI gate | done |
| 4 | Advanced retrieval | measured comparison vs baseline; ADR-0002 | done |
| 5 | Agents + HITL | e2e check on synthetic policies finds every known gap; node tests | done |
| 6 | MCP | tools callable from an MCP client; auth + tests | done |
| 7 | Optimisation | benchmark report before/after | done (offline); quantisation run *(you, needs Ollama)* |
| 8 | Security | `tests/security` passes; threat model | done |
| 9 | Observability + deploy | `helm lint`/`template` pass; dashboard JSON | done; kind install + screenshots *(you, needs Docker)* |
| 10 | Polish + launch | stranger can clone, run, reproduce evals | done; demo GIF, blog, profile *(you)* |

## Phase checklists

### Phase 0 - Foundation
- [x] src/ layout, pyproject (uv), ruff/mypy/pytest config, Makefile
- [x] pre-commit (ruff, mypy, gitleaks), `.env.example`, LICENSE, SECURITY, CONTRIBUTING
- [x] CI: lint + types + tests + coverage; gitleaks; Docker build + Trivy; CodeQL; Dependabot
- [x] `/health` endpoint and tests; CLAUDE.md; ADR template

### Phase 1 - Ingestion
- [x] `data/scripts/download_sources.py` (eCFR API) and sample corpus in `data/samples`
- [x] eCFR XML parser (native structure), Markdown parser, Docling path for PDF/HTML/DOCX
- [x] Structure-aware chunker (sections, whole tables, 300-800 tokens, heading path) + fixed baseline
- [x] Metadata schema: source, act, citation, section, jurisdiction, effective_date, version, tenant_id, allowed_groups
- [x] Pipeline -> JSONL catalogue, Qdrant and OpenSearch adapters; ADR-0001

### Phase 2 - Baseline RAG and API
- [x] VectorRetriever with server-side SecurityContext filters
- [x] `prompts/answer.v1.md`; numbered context; citations mapped to real chunk ids; abstention
- [x] `POST /v1/ask`, `POST /v1/ask/stream` (SSE), API-key auth -> tenant, request ids, `/health`, `/ready`
- [x] Docker Compose stack; integration tests

### Phase 3 - Evaluation
- [x] Golden set (71 items, 63 answerable) with verbatim-evidence validation *(extend to 150-300 - you)*
- [x] hit@k, recall@k, MRR, AP with hand-computed tests; generation proxies; optional RAGAS + judge
- [x] `run_eval.py` -> summary.json, HTML report (per-tag, worst-20), comparison.md; thresholds; eval.yml

### Phase 4 - Advanced retrieval
- [x] BM25, hybrid RRF, lexical + cross-encoder rerankers, query rewriting (gateway, cached), filters
- [x] Five-configuration comparison table; ADR-0002

### Phase 5 - Agents with human-in-the-loop
- [x] compliance_check graph with typed state, step limits, error routing, `interrupt()` review
- [x] Memory / Postgres checkpointer; `POST /v1/checks`, `GET /v1/checks/{id}`, `POST /v1/checks/{id}/review`
- [x] checklist_and_testgen graph with schema + AST validation; e2e on 7 synthetic documents

### Phase 6 - MCP
- [x] FastMCP server (stdio + streamable HTTP with bearer-token auth); tools validated, authorised, audited
- [x] Tests through a real MCP client session; `docs/mcp.md`; MCP client for downstream tools

### Phase 7 - Optimisation
- [x] Gateway with aliases, routing, fallbacks, budgets, timeouts; exact + semantic cache; compression
- [x] `benchmarks/run_bench.py` -> results JSON/Markdown
- [ ] q4 / q8 / fp16 comparison on Ollama *(you: `make up`, pull models, run with `--quant-models`)*

### Phase 8 - Security
- [x] PII redaction (regex + Presidio), injection scanner, `wrap_untrusted`, output validation, quarantine
- [x] Tests: tenant isolation, PII canaries, indirect injection, output neutralisation, auth/inputs
- [x] promptfoo red-team config; threat model (STRIDE + OWASP LLM Top 10)

### Phase 9 - Observability and deployment
- [x] OTel spans across API -> retrieval -> gateway -> agents; Langfuse; Prometheus metrics; Grafana JSON
- [x] Helm chart (api, mcp, worker; HPA, probes, limits, non-root, NetworkPolicy, PDB, ExternalSecret)
- [x] release.yml (images on tags), Terraform (optional)
- [ ] `helm install` on kind + dashboard screenshots *(you: needs Docker)*

### Phase 10 - Polish and launch
- [x] README from real reports, architecture docs, ADRs, runbook, CHANGELOG
- [ ] demo GIF/video, blog post, profile README published, pinned repos *(you)*
