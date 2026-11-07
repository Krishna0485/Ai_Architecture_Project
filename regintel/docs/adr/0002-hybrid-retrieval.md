# ADR-0002: Hybrid retrieval (BM25 + vectors, RRF) with reranking

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
Compliance questions mix exact legal vocabulary ("notification event", "825.110", "1,250 hours")
with paraphrase ("how soon must we tell the FTC about a breach"). Pure dense retrieval misses
exact terms and section numbers; pure keyword search misses paraphrase.

## Options considered
1. Vector-only. 2. BM25-only. 3. Hybrid with weighted score fusion. 4. **Hybrid with
   Reciprocal Rank Fusion (RRF)**. 5. Any of the above + a second-stage reranker.

**Why RRF over weighted fusion:** BM25 scores are unbounded and corpus-dependent while cosine
similarity is in [-1, 1]; weighted fusion needs per-corpus score normalisation and weight tuning
that drifts as the corpus grows. RRF uses ranks only (`1/(k + rank)`, k=60), needs no
calibration, and is robust when one retriever returns garbage.

## Decision
`hybrid` (BM25 + vector, RRF) followed by a reranker (`LexicalReranker` offline,
`CrossEncoderReranker` in full mode) is the production configuration (`hybrid+rerank`), and it
is the configuration the CI gate applies to. Query rewriting stays optional (off by default).

## Evidence
`evals/reports/comparison.md` (2026-11-07, golden_qa v1.0, 63 answerable questions, lite mode):

| Configuration | hit@5 | MRR | Context precision | Citation precision | Abstention acc. |
|---|---|---|---|---|---|
| vector | 0.95 | 0.79 | 0.76 | 0.73 | 0.93 |
| bm25 | 0.98 | 0.92 | 0.90 | 0.76 | 0.97 |
| hybrid | 0.98 | 0.90 | 0.85 | 0.76 | 0.94 |
| hybrid+rerank | 0.98 | 0.92 | 0.90 | 0.78 | 0.97 |
| hybrid+rerank+rewrite | 0.98 | 0.92 | 0.90 | 0.79 | 0.97 |

Honest reading of these numbers:
- Hybrid+rerank beats the vector baseline clearly (MRR 0.79 -> 0.92, context precision
  0.76 -> 0.90).
- **BM25 alone is about as strong as hybrid+rerank on this corpus.** In lite mode the "dense"
  retriever is feature hashing (lexical), so it adds little semantic signal; the corpus is small
  (65 chunks) and questions reuse regulatory vocabulary. Hybrid fusion without reranking is
  slightly *worse* than BM25 because the weaker retriever's ranks dilute BM25's.
- The reranker recovers that loss and gives the best citation precision.

## Consequences
- Positive: one pipeline handles exact-term and paraphrase queries; every stage is switchable
  for evaluation (`RetrievalConfig`).
- Negative: two indexes to maintain; reranking adds latency (p95 roughly doubles in lite mode).
- Follow-ups: rerun with BGE embeddings + cross-encoder (full mode) and paraphrase-heavy
  questions, where dense retrieval is expected to matter more; if BM25 still matches hybrid,
  consider BM25 + rerank to cut cost.

## How we will know it was right
`make eval` in full mode with a paraphrase-tagged slice of the golden set.
