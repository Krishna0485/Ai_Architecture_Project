# ADR-0008: Abstention by IDF-weighted query coverage

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The system must say "I don't know" instead of answering from loosely related passages. Raw
retrieval scores are not comparable across configurations (RRF scores, cosine, BM25, reranker
scores all differ), so "top score < threshold" is ill-defined in a configurable pipeline.

## Options considered
1. Threshold on the first-stage score - differs per retriever; breaks when the config changes.
2. Plain query-term coverage of the best passage - stage-independent, but generic words dominate:
   in our first eval run, "What is the minimum wage in California in 2026?" was answered from an
   FMLA/FLSA passage, and so were two other out-of-scope questions.
3. **IDF-weighted coverage** - weight each query term by its corpus IDF; terms absent from the
   corpus get the maximum weight. Missing rare terms ("California", "GDPR") sink confidence.
4. An LLM "is this answerable?" judge - strongest, but adds a model call to every request.

## Decision
Option 3 (`AnswerService.confidence`), threshold `min_score = 0.40`, plus a second guard: an
answer with no valid citation is converted into an abstention. Redaction placeholders (`<EMAIL>`)
are excluded from scoring.

## Evidence
Measured during development on 2026-11-07 (golden_qa v1.0, hybrid+rerank): abstention accuracy
0.958 with plain coverage vs 0.972 with IDF weighting, same code otherwise. The committed
`evals/reports/summary.json` reflects the IDF-weighted version only.

## Consequences / known limitations
- The threshold was chosen on the same golden set it is evaluated on (risk of overfitting);
  re-validate on every dataset extension and keep a held-out slice.
- One known miss: "What escalation code does Globex use...?" (asked as tenant Acme) is answered
  from Acme's own guidance because every term except the entity name matches. Corpus statistics
  are global, so the unseen-entity signal is weaker than it should be.
- Follow-up: entity-aware abstention (named entities in the query must appear in the context)
  or option 4 for low-confidence bands only.
