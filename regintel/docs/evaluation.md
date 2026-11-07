# Evaluation

`make eval` reproduces every quality number in the README. The run is deterministic in lite
mode (no network, no model sampling).

## Datasets

### Golden Q&A (`evals/datasets/golden_qa.jsonl`, v1.0)
- 71 items: 63 answerable (25 GLBA Safeguards, 24 FMLA, 13 Reg B, 1 tenant-private) and 8
  unanswerable (out-of-corpus topics plus one cross-tenant probe).
- Source of truth is `golden_qa.source.yaml`; `make golden` builds the JSONL and **validates**
  that each item's `evidence` phrase appears verbatim in one of its `relevant_sections` (this
  caught 3 wrong references while building v1.0).
- Fields: `id, question, reference_answer, relevant_sections, evidence, tags, answerable`.
- Relevance is **section-level** (`<source>:<section>`), so labels survive re-chunking.

**How items were written.** Questions were drafted from the regulation text section by section,
covering definitions, thresholds, deadlines, exceptions and obligations. Reference answers
paraphrase the regulation; the `evidence` phrase is copied verbatim.

**Avoiding overfitting.** Retrieval/abstention parameters (`min_score`, reranker weights) were
tuned on this set, so v1.0 numbers are optimistic. Before quoting results externally:
(1) extend to 150-300 items with `golden_qa_template.csv`, (2) hold out a slice that is never
used for tuning, (3) add paraphrase-heavy questions written without looking at the text.

### Agent check cases (`evals/datasets/check_cases.jsonl`)
7 synthetic policies (3 with exactly 3 known gaps each, 1 of them with a prompt injection, 3
compliant controls). Metrics: gap recall, gap precision, task success (exact gap set), steps.

## Metrics

| Metric | Definition | Implementation |
|---|---|---|
| hit@5 | 1 if any of the top-5 chunks is from a relevant section | `evals/metrics/retrieval.py` |
| recall@10 | share of relevant sections found in the top-10 | same |
| MRR | 1 / rank of the first relevant chunk (top-10) | same |
| context precision | rank-aware precision (AP@5) of the passages given to the generator | same |
| context recall | share of relevant sections present in the generator's context | same |
| faithfulness* | share of answer sentences whose content terms are >= 60% covered by the cited passages | `evals/metrics/generation.py` |
| answer relevancy* | share of question content terms addressed by the answer | same |
| answer F1 | token F1 vs the reference answer | same |
| citation precision | share of citations pointing to a relevant section | `run_eval.py` |
| abstention accuracy | correct abstain/answer decisions over all items | `run_eval.py` |
| judge score | LLM-as-judge 1-5 rubric (normalised), `--judge` | `evals/metrics/judge.py` |
| RAGAS | faithfulness, answer relevancy, context precision/recall with a judge LLM | `evals/metrics/ragas_runner.py` |

\* Lexical proxies with the same intent as the RAGAS metrics. They are deterministic and cheap,
which is what a per-PR gate needs, but they are not equivalent: with the offline extractive
generator, faithfulness is ~1.0 by construction. Use RAGAS / the judge with a real model for
generation quality.

### Judge calibration
Before trusting a judge model: score 30-50 answers by hand (1-5), run `--judge`, and report
agreement (Spearman rho and exact/within-1 agreement). Re-calibrate when the judge model or
`prompts/judge.v1.md` changes. Never let the judge be the same model that generated the answers
without noting it.

## Configurations compared
`vector`, `bm25`, `hybrid` (RRF), `hybrid+rerank` (production / gate), `hybrid+rerank+rewrite`,
plus a chunking experiment (structure-aware vs fixed 400-token windows).

## Gates (`evals/thresholds.yaml`)
Applied to `hybrid+rerank` and the check suite. CI (`eval.yml`) runs a stratified 30-question
subset + the check suite on PRs touching retrieval/generation/agents/prompts/evals, and the full
suite nightly. Regression rules compare with the previous summary on the same dataset
fingerprint.

The `answer_relevancy` gate is 0.75: the lexical proxy's v1.0 baseline (0.778) minus a margin,
because extractive answers rarely restate the question. Raise it to 0.85 when gating on RAGAS
answer relevancy with a real model.

## Reports
- `evals/reports/summary.json` - all metrics, per-tag breakdown, worst-20, gate result.
- `evals/reports/latest.html` (+ dated copy) - human-readable report.
- `evals/reports/comparison.md` - the tables copied into the README.

## Adding cases
1. Add items to `golden_qa.source.yaml` (or fill the CSV template and convert).
2. `make golden` - fix any evidence/section errors it reports.
3. `make eval`, inspect the worst-20 table, and commit dataset + reports together.
