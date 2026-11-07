# Contributing

## Setup

```bash
make setup          # uv sync --all-groups && pre-commit install
make test           # unit + security tests
make lint           # ruff + mypy --strict
```

## Workflow

1. Open (or pick) an issue; one feature or fix per branch: `feat/<topic>`, `fix/<topic>`.
2. Plan first for anything non-trivial; record significant decisions as an ADR
   (`docs/adr/template.md`).
3. Write tests with the change: unit tests mirror the `src/` path; security behaviour goes in
   `tests/security`; no network in unit tests (use fakes in `tests/fixtures`).
4. If you touch `src/regintel/retrieval`, `src/regintel/generation`, `prompts/` or `evals/`,
   run `make eval` and include the metric deltas in the PR.
5. Use [Conventional Commits](https://www.conventionalcommits.org): `feat:`, `fix:`, `test:`,
   `docs:`, `refactor:`, `ci:`, `chore:`.
6. CI must be green (lint, types, tests, coverage >= 80%, eval gate, gitleaks, Trivy).

## Rules that reviewers enforce

- All config through `regintel.config.Settings`; never read `os.environ` elsewhere.
- All model calls through `regintel.llm.gateway`; prompts live in `prompts/*.vN.md`.
- Security filters come from `SecurityContext`, never from user text or model output.
- Every tool validates args, checks policy and writes an audit event.
- Never change `evals/thresholds.yaml` or golden datasets without an explicit, documented decision.
- Numbers in README/docs must be copied from `evals/reports` or `benchmarks/results`.
