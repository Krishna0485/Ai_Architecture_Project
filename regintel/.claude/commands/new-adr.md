---
description: Draft an ADR from a short decision description
argument-hint: <short decision, e.g. "use RRF instead of weighted score fusion">
---
Draft a new Architecture Decision Record for: $ARGUMENTS

1. Read docs/adr/template.md and list docs/adr/ to pick the next number (NNNN).
2. Gather evidence from the repo: relevant code, evals/reports/summary.json,
   benchmarks/results/latest.md. Quote only numbers that exist in those files.
3. Write docs/adr/NNNN-<slug>.md with Status "Proposed", Context, Options considered (with
   trade-offs), Decision, Consequences (positive/negative), and How we'll know (metric/test).
4. Add the ADR to the list in docs/architecture.md and README "Design decisions".
5. Show me the draft; I will rewrite the reasoning in my own words before accepting it.
