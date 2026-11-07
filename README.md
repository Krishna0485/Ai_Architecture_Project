# GitHub portfolio workspace

Built from my GitHub portfolio build plan. All three projects live in this monorepo; CI runs
per project via path filters in `.github/workflows/`.

| Folder | Project | Status |
|---|---|---|
| `regintel/` | flagship: agentic compliance intelligence platform | complete; 138 tests, 97% coverage, eval gate passing |
| `rag-eval-kit/` | RAG evaluation library + CLI | complete; 10 tests, 100% coverage |
| `regintel-mcp-servers/` | secure MCP servers (docstore, checklist, ticketing) | complete; 15 tests, 95% coverage |
| `github-profile/` | profile README + resume/interview guide | fill in your username/links |

## Verify locally

```bash
cd regintel && uv sync --all-groups && uv run pytest && uv run python evals/run_eval.py && uv run python benchmarks/run_bench.py
cd ../rag-eval-kit && uv sync --group dev && uv run pytest
cd ../regintel-mcp-servers && uv sync --group dev && uv run pytest
```

## What needs you (accounts, hardware or judgement)

1. Fill in your LinkedIn/blog links in `github-profile/README.md` (repo links already point here).
2. Tag releases: a `regintel-v1.0.0` tag triggers the release workflow (images to GHCR +
   GitHub Release with the eval summary).
3. Run full mode once: `cd regintel && cp .env.example .env && make up`, pull the Ollama models,
   then `REGINTEL_LLM_PROVIDER=openai_compatible make eval` and `make bench --quant-models ...`.
   Put those model-quality numbers in the README next to the lite-mode ones.
4. `make kind-up && make helm-install`, then capture the Grafana/Langfuse screenshots and the demo
   GIF (`regintel/docs/images/README.md`).
5. Review and extend the golden set (`regintel/evals/datasets/golden_qa.source.yaml`) to 150-300
   items with a held-out slice. Re-read every ADR and rewrite the reasoning in your own words.
6. Publish the blog post, set repo topics and social previews, and pin the three repos.
