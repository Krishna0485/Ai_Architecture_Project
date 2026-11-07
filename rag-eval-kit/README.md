# rag-eval-kit

> A small, dependency-free library and CLI for benchmarking RAG pipelines: retrieval quality,
> answer quality, abstention, latency and cost, plus CI gates and an HTML report.

[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Extracted from the evaluation framework of [RegIntel](https://github.com/Krishna0485/Ai_Architecture_Project/tree/main/regintel). It is
system-agnostic: your pipeline writes one JSON line per question, and rag-eval-kit does the rest.

## Why
- **Reproducible:** the core is stdlib-only and deterministic, so it suits a per-PR CI gate.
- **Honest:** generation metrics are computed only on answered items, and abstention is scored
  separately, so a system can't game faithfulness by refusing hard questions.
- **Comparable:** pass several prediction files and get one comparison table and report.

## Quickstart

```bash
pip install -e .            # or: uv sync
rag-eval run --dataset examples/dataset.jsonl \
  --predictions examples/predictions_hybrid.jsonl \
  --predictions examples/predictions_vector.jsonl \
  --out report/ --gate hit_at_5=0.8
```

Output: `report/summary.json`, `report/comparison.md`, `report/report.html`. Gates apply to the
first `--predictions` file; the exit code is 1 when one fails, so it plugs straight into CI
(swap the two files above to see the vector run fail the gate). Add `--baseline
old/summary.json --max-drop 0.03` for regression checks.

The example files are illustrative, hand-written predictions shaped like RegIntel output; they
are not benchmark results.

## Formats

```jsonc
// dataset.jsonl - reference_answer: null marks an unanswerable question
{"id": "q1", "question": "...", "reference_answer": "...", "relevant_ids": ["doc:section"], "tags": ["fmla"]}
// predictions.jsonl
{"id": "q1", "retrieved_ids": ["..."], "answer": "...", "contexts": ["..."], "abstained": false,
 "latency_ms": 820, "prompt_tokens": 2100, "completion_tokens": 40, "cost_usd": 0.0069}
```

## Library

```python
from rag_eval_kit import evaluate, load_jsonl

res = evaluate(load_jsonl("dataset.jsonl"), load_jsonl("preds.jsonl"), k=5, name="hybrid")
print(res.metrics["mrr"], res.per_tag["fmla"])
```

- `rag_eval_kit.metrics`: hit@k, recall@k, precision@k, MRR, AP, nDCG@k, faithfulness /
  relevancy proxies, answer F1, percentiles ([definitions](docs/metrics.md))
- `rag_eval_kit.judge`: rubric LLM-as-judge for any `callable(prompt) -> str`, plus
  `calibrate()` (Spearman, agreement, bias) against human labels
- `rag_eval_kit.ragas_runner`: optional RAGAS adapter (`pip install rag-eval-kit[ragas]`)
- `rag_eval_kit.report`: Markdown table and self-contained HTML (light/dark, escaped)

## Development

```bash
uv sync --group dev && uv run pytest && uv run ruff check . && uv run mypy
```

MIT licensed.
