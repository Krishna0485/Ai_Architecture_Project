# Runbook

## Local (lite mode, no Docker)

```bash
make setup                 # uv sync --all-groups + pre-commit
make ingest                # optional: persists data/index/chunks.jsonl (API ingests samples if absent)
make dev                   # API on http://localhost:8080 (OpenAPI at /docs)
curl -s localhost:8080/v1/ask -H 'X-API-Key: dev-key-acme' -H 'content-type: application/json' \
  -d '{"question":"When must the FTC be notified of a notification event?"}' | jq
make ui                    # Streamlit UI (needs the ui extra)
make test && make eval && make bench
```

On Windows without `make`, run the commands inside each target directly, e.g.
`uv run uvicorn regintel.api.main:app --port 8080`.

## Full stack (Docker Compose)

```bash
cp .env.example .env       # set LITELLM_MASTER_KEY, REGINTEL_GATEWAY_API_KEY, REGINTEL_API_KEYS
make up                    # api, mcp, gateway (LiteLLM), ollama, qdrant, postgres, redis
docker compose -f infra/compose/docker-compose.yml exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose -f infra/compose/docker-compose.yml exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
make up-obs                # + otel-collector, jaeger :16686, prometheus :9090, grafana :3001, langfuse :3000
```

Queue mode for long checks: `docker compose --profile queue up -d worker` and set
`REGINTEL_CHECK_EXECUTOR=queue`.

## Kubernetes (kind)

```bash
make kind-up
kubectl create namespace regintel
kubectl -n regintel create secret generic regintel-secrets \
  --from-literal=REGINTEL_API_KEYS='{"<random-key>":{"tenant_id":"acme","groups":["compliance","admin"]}}'
make helm-install          # builds image, loads into kind, installs with values-local.yaml
kubectl -n regintel port-forward svc/regintel-api 8080:80
```

Production values (`values.yaml`) expect Qdrant, Redis, Postgres, LiteLLM and an OTel collector
in-cluster or managed, and a Secret (or ExternalSecret) named `regintel-secrets`.

## Operations

| Task | How |
|---|---|
| Kill switch for agents | set `REGINTEL_AGENTS_ENABLED=false` (Helm: `--set config.REGINTEL_AGENTS_ENABLED=false`); checks/checklists return 503, Q&A keeps working |
| Rotate an API key | update `REGINTEL_API_KEYS` secret, restart pods (rolling) |
| Re-index | `make data && make ingest` (Qdrant point ids are deterministic, so re-runs upsert) |
| Cap spend | lower `REGINTEL_TENANT_DAILY_TOKEN_BUDGET`; LiteLLM `max_budget` in `infra/litellm.yaml` |
| Switch models | edit aliases in `infra/litellm.yaml`; no code change |
| Inspect a request | response headers `x-request-id` and `x-trace-id` -> Jaeger / Langfuse; audit via `GET /v1/admin/audit` |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/ready` reports `not_ready` | empty index | `make ingest`, or check `REGINTEL_INDEX_PATH` |
| Many abstentions | question outside corpus, or `min_score` too high | inspect `confidence` in the response; `make eval` before changing the threshold |
| 503 "model unavailable" | gateway/Ollama down, all fallbacks failed | `docker compose logs gateway ollama`; models pulled? |
| 429 | token budget exceeded | raise budget or wait for the daily window |
| Check stuck in `running` | worker not running (queue mode) | start worker; checks resume from the Postgres checkpoint |
| MCP client sees no tools | wrong transport/identity | stdio needs `REGINTEL_MCP_DEFAULT_API_KEY`; HTTP needs `Authorization: Bearer <key>` |
