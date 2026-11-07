| Configuration | p50 | p95 | Throughput | LLM calls | Tokens/req | Cache hit | Est. cost / 1K req |
|---|---|---|---|---|---|---|---|
| baseline | 153.4 ms | 331.5 ms | 23.5 rps | 603 | 3730 | 0% | $12.48 |
| +compression | 151.4 ms | 332.9 ms | 23.1 rps | 603 | 2282 | 0% | $8.16 |
| +routing | 153.1 ms | 344.7 ms | 23.2 rps | 603 | 2282 | 0% | $7.53 |
| +semantic_cache | 26.9 ms | 254.1 ms | 63.8 rps | 113 | 385 | 82% | $1.32 |

300 requests, concurrency 4, provider `heuristic`, pricing (USD/1M in,out) {'fast': (0.0, 0.0), 'smart': (3.0, 15.0), 'heuristic': (0.0, 0.0)}. Generated 2026-11-07T07:37:41Z by `make bench`.
Latency reflects retrieval + orchestration only (offline deterministic model); token counts and cost are computed from real prompt sizes.
