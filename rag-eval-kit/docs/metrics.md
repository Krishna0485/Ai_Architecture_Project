# Metric definitions

Notation: `ranked` = ids returned by the retriever in order; `R` = set of relevant ids;
`k` = cut-off (default 5). Retrieval metrics are computed on answerable items only.

| Metric | Formula | Notes |
|---|---|---|
| hit@k | 1 if `ranked[:k] ∩ R ≠ ∅` else 0 | "did we find anything useful?" |
| recall@k | \|set(ranked[:k]) ∩ R\| / \|R\| | coverage when several sources are needed |
| precision@k | \|ranked[:k] ∩ R\| / k | noise in the context window |
| MRR | 1 / rank of the first relevant id (0 if none in top-k) | rewards putting the best evidence first |
| context precision (AP@k) | mean over relevant positions i <= k of precision@i | rank-aware precision, as in RAGAS |
| nDCG@k | Σ 1/log2(i+1) over relevant hits / ideal DCG | binary relevance; duplicates count once |
| faithfulness (proxy) | share of answer sentences with >= 60% of content terms present in the contexts | lexical, deterministic; RAGAS uses an LLM to verify claims |
| answer relevancy (proxy) | share of question content terms present in the answer | RAGAS generates questions from the answer and compares embeddings |
| answer F1 | token F1 between answer and reference (SQuAD style) | penalises verbosity and omissions |
| abstention accuracy | share of items where `abstained == (reference is null)` | measures "knowing when not to answer" |
| p50 / p95 latency | nearest-rank percentiles of `latency_ms` | |
| tokens / request | mean prompt + completion tokens | |
| cost / 1K requests | mean `cost_usd` × 1000 | supply cost per prediction from your gateway |

## Generation metrics are computed on answered items only
An abstention is not "unfaithful"; it is scored by abstention accuracy instead. This prevents a
system from gaming faithfulness by abstaining on hard questions while still exposing excessive
abstention (false abstentions lower abstention accuracy).

## Lexical proxies vs RAGAS / LLM judges
Proxies are free, deterministic and good CI gates for regressions; they are not a substitute
for model-judged quality. Use `rag_eval_kit.ragas_runner.run_ragas` or the judge with a
calibrated model for release reports.

## Judge calibration
`rag-eval calibrate --labels labels.jsonl` reports Spearman ρ, exact and within-one agreement,
and mean bias (judge − human; positive = lenient judge). Collect 30-50 human labels per judge
model/prompt version; re-calibrate whenever either changes.
