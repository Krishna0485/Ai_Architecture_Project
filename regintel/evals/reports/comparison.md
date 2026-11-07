| Configuration | hit@5 | recall@10 | MRR | Context precision | Faithfulness* | Answer relevancy* | Citation precision | Abstention acc. | p95 latency |
|---|---|---|---|---|---|---|---|---|---|
| vector | 0.95 | 1.00 | 0.79 | 0.76 | 1.00 | 0.79 | 0.73 | 0.93 | 41 ms |
| bm25 | 0.98 | 1.00 | 0.92 | 0.90 | 1.00 | 0.77 | 0.76 | 0.97 | 27 ms |
| hybrid | 0.98 | 1.00 | 0.90 | 0.85 | 1.00 | 0.78 | 0.76 | 0.94 | 38 ms |
| hybrid+rerank | 0.98 | 1.00 | 0.92 | 0.90 | 1.00 | 0.77 | 0.78 | 0.97 | 66 ms |
| hybrid+rerank+rewrite | 0.98 | 1.00 | 0.92 | 0.90 | 1.00 | 0.77 | 0.79 | 0.97 | 65 ms |

Dataset: golden_qa v1.0, 71 questions (63 answerable). LLM provider: heuristic. *Lexical proxy metrics (see docs/evaluation.md). Generated 2026-11-07T07:36:22Z by `make eval`.

| Agent check suite | Gap recall | Gap precision | Task success | Mean steps |
|---|---|---|---|---|
| compliance_check (7 synthetic docs) | 1.00 | 1.00 | 1.00 | 7.0 |

| Chunking (hybrid+rerank) | chunks | hit@5 | MRR | Faithfulness* | Citation precision |
|---|---|---|---|---|---|
| structure_aware | 65 | 0.98 | 0.92 | 1.00 | 0.78 |
| fixed_400 | 85 | 0.90 | 0.75 | 1.00 | 0.59 |
