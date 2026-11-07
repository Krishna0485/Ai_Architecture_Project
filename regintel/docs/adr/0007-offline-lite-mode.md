# ADR-0007: Offline "lite mode" with a deterministic heuristic provider

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
CI must be hermetic (no GPUs, no API keys, no network) and reproducible, and a reviewer must be
able to clone the repo and run tests and evals in minutes. Real LLM output is non-deterministic
and costly.

## Decision
Every external dependency has an in-process stand-in behind the same Protocol:
hashing embedder, in-memory vector store, in-process BM25, lexical reranker, in-memory caches,
memory checkpointer, JSONL audit, and `HeuristicProvider` - a transparent rule-based stand-in
for each LLM task (extractive answers, keyword/numeric compare, etc.). Full mode is selected by
configuration only.

## Consequences
- Positive: `make test` and `make eval` run in about a minute on a laptop; the eval gate guards
  the *pipeline* (retrieval, grounding, abstention, tenancy, orchestration) on every PR.
- Negative: lite-mode generation metrics are not model quality. Faithfulness is ~1.0 because
  the stand-in answers extractively; the agent check suite passes partly because the stand-in's
  compare rules were written alongside the catalogue. **Do not quote lite-mode generation or
  check-suite numbers as LLM quality.** Measure model quality with `REGINTEL_LLM_PROVIDER=
  openai_compatible make eval`.
- Follow-ups: nightly full-mode eval on a self-hosted runner with Ollama.
