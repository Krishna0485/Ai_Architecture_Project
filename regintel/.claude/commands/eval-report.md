---
description: Run the evaluation, compare with the previous summary and draft a changelog entry
---
1. Copy evals/reports/summary.json to /tmp/summary.prev.json (if it exists).
2. Run `make eval`. If the gate fails, stop and show the failures.
3. Compare the new summary with the previous one for every configuration: hit_at_5, mrr,
   context_precision, faithfulness, answer_relevancy, abstention_accuracy, p95_latency_ms, and
   the checks suite. Present a table of deltas (new - old) and flag drops beyond
   evals/thresholds.yaml regression limits.
4. Draft a CHANGELOG.md "Unreleased" entry summarising what changed and the measured effect.
   Use only numbers from the two summaries.
5. Update README results tables from evals/reports/comparison.md if they differ.
