# Benchmarks

`make bench` runs `benchmarks/run_bench.py` and writes `benchmarks/results/<date>.json`,
`<date>.md` and `latest.md`.

## Method
- **Workload:** 300 requests drawn from the 63 answerable golden questions with a Zipf-like
  distribution (exponent 1.1, seed 11) - popular questions repeat, as in help-desk traffic.
- **Concurrency:** 4 worker threads; 3 warm-up queries are excluded.
- **Configurations (cumulative):** `baseline` (no cache, no compression, every task on `smart`)
  -> `+compression` (context trimmed to 1,800 tokens) -> `+routing` (rewrite on `fast`) ->
  `+semantic_cache` (tenant-namespaced semantic cache + exact LLM cache). All use
  hybrid+rerank+rewrite retrieval so both model routes are exercised.
- **Tokens** are counted from the real rendered prompts and completions.
- **Cost** is an *estimate*: tokens x `Settings.pricing` (USD per 1M input/output tokens).
  Defaults: `smart` = $3 / $15 (hosted frontier-class model), `fast` = $0 (local quantised
  model). Change the pricing table to match your models.

## Interpreting lite-mode results
With the offline provider, latency measures retrieval + orchestration only (no model inference),
so absolute latencies are far lower than with a real model; relative effects of caching are
still real. Token, call-count and cache numbers are real. Cache hit rate depends heavily on
traffic; the Zipf workload is repeat-heavy by design.

## Quantisation comparison (needs Ollama)
```bash
make up   # then pull the models listed in infra/litellm.yaml
REGINTEL_LLM_PROVIDER=openai_compatible uv run python benchmarks/run_bench.py \
  --quant-models smart,smart-q8,smart-fp16
REGINTEL_LLM_PROVIDER=openai_compatible make eval   # quality per quantisation level
```
Report latency/throughput from the benchmark and quality deltas from `make eval` side by side;
choose the lowest-precision level whose eval metrics stay within the regression limits.
