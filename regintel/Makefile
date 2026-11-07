.PHONY: setup data ingest dev test itest e2e eval eval-fast bench up up-obs down lint fmt mcp ui \
        golden kind-up helm-install helm-uninstall clean

COMPOSE := docker compose -f infra/compose/docker-compose.yml
COMPOSE_OBS := $(COMPOSE) -f infra/compose/docker-compose.observability.yml

setup:          ## install deps + git hooks
	uv sync --all-groups
	uv run pre-commit install

lint:           ## ruff + format check + mypy --strict (must pass before commit)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt:
	uv run ruff check . --fix
	uv run ruff format .

test:           ## unit + security tests (no network)
	uv run pytest tests/unit tests/security

itest:          ## integration tests (in-process stack; docker-marked tests need `make up`)
	uv run pytest tests/integration tests/e2e --no-cov

data:           ## download eCFR sources (full -> data/raw, sample -> data/samples) + synthetic docs
	uv run python data/scripts/download_sources.py
	uv run python data/scripts/download_sources.py --sample
	uv run python data/scripts/generate_synthetic_docs.py

ingest:         ## parse, chunk and index the sample corpus
	uv run python -m regintel.ingestion.pipeline --source data/samples

golden:         ## rebuild + validate the golden dataset from its YAML source
	uv run python evals/datasets/build_golden.py

eval:           ## full evaluation; writes evals/reports/summary.json + HTML
	uv run python evals/run_eval.py --dataset evals/datasets/golden_qa.jsonl

eval-fast:      ## CI gate on a 30-question stratified subset
	uv run python evals/run_eval.py --subset 30 --configs hybrid_rerank --suites retrieval,checks

bench:          ## latency / throughput / tokens / cache / cost benchmarks
	uv run python benchmarks/run_bench.py

dev:            ## API with auto-reload on :8080
	uv run uvicorn regintel.api.main:app --reload --port 8080

mcp:            ## MCP server over stdio (set REGINTEL_MCP_DEFAULT_API_KEY)
	uv run python -m regintel.mcp_server --transport stdio

ui:
	uv run --extra ui streamlit run ui/streamlit_app.py

up:             ## core docker stack
	$(COMPOSE) up -d --build

up-obs:         ## core stack + Langfuse, Prometheus, Grafana, OTel collector
	$(COMPOSE_OBS) up -d --build

down:
	$(COMPOSE_OBS) down

kind-up:        ## local Kubernetes cluster
	kind create cluster --name regintel --config infra/k8s/kind-config.yaml

helm-install:   ## build images, load into kind, install chart
	docker build -f infra/docker/Dockerfile.api -t regintel-api:local .
	kind load docker-image regintel-api:local --name regintel
	helm upgrade --install regintel infra/k8s/helm/regintel -n regintel --create-namespace \
	  -f infra/k8s/helm/regintel/values-local.yaml

helm-uninstall:
	helm uninstall regintel -n regintel

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml data/index
