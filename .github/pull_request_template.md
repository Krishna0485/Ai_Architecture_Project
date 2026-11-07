## What & why

<!-- One or two sentences. Link the issue: Closes #123 -->

## Changes

-

## Evidence

- [ ] `make lint` and `make test` pass locally
- [ ] Tests added/updated (unit mirrors src path; security behaviour in `tests/security`)
- [ ] If retrieval/generation/prompts/evals changed: `make eval` run, deltas pasted below
- [ ] If a significant decision was made: ADR added under `docs/adr/`

| Metric (hybrid_rerank) | Before | After |
|---|---|---|
| hit@5 | | |
| MRR | | |
| faithfulness | | |

## Self-review

- [ ] No secrets, PII or large files; `.env` untouched
- [ ] Config via `Settings`, LLM calls via the gateway, prompts in `prompts/`
- [ ] Tool args validated, policy checked, audit event written
- [ ] Docs/README updated (no invented numbers)
