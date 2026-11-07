# ADR-0001: Structure-aware chunking

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
Regulations are hierarchical (part > subpart > section > paragraph) and answers must cite a
section. Fixed windows split paragraphs mid-sentence, merge unrelated sections and attribute a
chunk to whichever section it starts in, which corrupts citations.

## Options considered
1. **Fixed-size windows** (400 tokens, 50 overlap) - simple, uniform sizes; ignores structure.
2. **Structure-aware** - never cross a section boundary, keep tables whole, pack paragraphs to
   300-800 tokens, split over-long paragraphs on sentence boundaries, prepend the heading path.
3. **Semantic chunking** (embedding-similarity breakpoints) - adaptive, but non-deterministic
   across embedding models and still unaware of legal structure.

## Decision
Structure-aware chunking (option 2), implemented in `ingestion/chunker.py`. eCFR XML is parsed
natively (DIV6/DIV8/GPOTABLE), so structure is exact rather than inferred. Chunk ids are
`<source>:<section>:<n>`, which makes citations stable and human-readable.

## Evidence
`evals/reports/summary.json` (2026-11-07, golden_qa v1.0, hybrid+rerank, lite mode):

| Chunker | chunks | hit@5 | MRR | Citation precision |
|---|---|---|---|---|
| structure_aware | 65 | 0.98 | 0.92 | 0.78 |
| fixed_400 | 85 | 0.90 | 0.75 | 0.59 |

## Consequences
- Positive: +0.17 MRR and +0.19 citation precision; citations map 1:1 to sections; tables
  (fee schedules, thresholds) survive intact.
- Negative: chunk sizes vary (31-813 tokens); very short sections become small chunks with less
  context; giant tables can exceed the context budget (compression then trims them).
- Follow-ups: parent-section expansion at generation time for short chunks; re-run this
  comparison with BGE embeddings.

## How we will know it was right
The chunking comparison is part of `make eval`; if a future chunker beats MRR/citation precision
on the same golden set, revisit.
