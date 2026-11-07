"""Join a dataset with a system's predictions and compute every metric.

Dataset JSONL:     {"id", "question", "reference_answer"|null, "relevant_ids": [...], "tags": [...]}
Predictions JSONL: {"id", "retrieved_ids": [...], "answer", "contexts": [...], "abstained"?,
                    "latency_ms"?, "cost_usd"?, "prompt_tokens"?, "completion_tokens"?}
An item with ``reference_answer: null`` is unanswerable: the correct behaviour is to abstain.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_eval_kit import metrics as m


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: invalid JSON ({exc.msg})") from exc
    return rows


@dataclass
class EvalResult:
    name: str
    metrics: dict[str, float]
    per_tag: dict[str, dict[str, float]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    missing_predictions: list[str] = field(default_factory=list)

    def to_dict(self, include_rows: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "metrics": self.metrics,
            "per_tag": self.per_tag,
            "missing_predictions": self.missing_predictions,
        }
        if include_rows:
            out["rows"] = self.rows
        return out


def _row(item: dict[str, Any], pred: dict[str, Any], k: int) -> dict[str, Any]:
    relevant = set(item.get("relevant_ids", []))
    ranked = list(pred.get("retrieved_ids", []))
    answer = str(pred.get("answer", ""))
    answerable = item.get("reference_answer") is not None
    abstained = bool(pred.get("abstained", False))
    row: dict[str, Any] = {
        "id": item["id"],
        "tags": item.get("tags", []),
        "answerable": answerable,
        "abstained": abstained,
        "abstention_correct": abstained != answerable,
        "latency_ms": float(pred.get("latency_ms", 0.0)),
        "cost_usd": float(pred.get("cost_usd", 0.0)),
        "tokens": int(pred.get("prompt_tokens", 0)) + int(pred.get("completion_tokens", 0)),
    }
    if answerable:
        row |= {
            f"hit_at_{k}": m.hit_at_k(ranked, relevant, k),
            f"recall_at_{k}": m.recall_at_k(ranked, relevant, k),
            "mrr": m.reciprocal_rank(ranked, relevant, k),
            f"ndcg_at_{k}": m.ndcg_at_k(ranked, relevant, k),
            "context_precision": m.average_precision(ranked, relevant, k),
        }
        if not abstained:
            row |= {
                "faithfulness": m.faithfulness(answer, list(pred.get("contexts", []))),
                "answer_relevancy": m.answer_relevancy(item["question"], answer),
                "answer_f1": m.answer_f1(answer, str(item["reference_answer"])),
            }
    return row


def _aggregate(rows: Iterable[dict[str, Any]], k: int) -> dict[str, float]:
    rows = list(rows)
    ans = [r for r in rows if r["answerable"]]
    answered = [r for r in ans if not r["abstained"]]
    out = {
        key: m.mean([r[key] for r in ans])
        for key in (f"hit_at_{k}", f"recall_at_{k}", "mrr", f"ndcg_at_{k}", "context_precision")
    }
    for key in ("faithfulness", "answer_relevancy", "answer_f1"):
        out[key] = m.mean([r[key] for r in answered])
    out["abstention_accuracy"] = m.mean([float(r["abstention_correct"]) for r in rows])
    lat = [r["latency_ms"] for r in rows]
    out["p50_latency_ms"] = m.percentile(lat, 50)
    out["p95_latency_ms"] = m.percentile(lat, 95)
    out["tokens_per_request"] = m.mean([float(r["tokens"]) for r in rows])
    out["cost_per_1k_usd"] = m.mean([r["cost_usd"] for r in rows]) * 1000
    out["n"] = float(len(rows))
    return {key: round(v, 4) for key, v in out.items()}


def evaluate(
    dataset: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    k: int = 5,
    name: str = "run",
) -> EvalResult:
    by_id = {p["id"]: p for p in predictions}
    rows, missing = [], []
    for item in dataset:
        pred = by_id.get(item["id"])
        if pred is None:
            missing.append(item["id"])
            pred = {"id": item["id"], "retrieved_ids": [], "answer": "", "abstained": True}
        rows.append(_row(item, pred, k))
    tags: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        for t in r["tags"]:
            tags.setdefault(t, []).append(r)
    per_tag = {t: _aggregate(rs, k) for t, rs in sorted(tags.items())}
    return EvalResult(name, _aggregate(rows, k), per_tag, rows, missing)


def check_gates(
    result: EvalResult,
    gates: dict[str, float],
    baseline: EvalResult | None = None,
    max_drop: float | None = None,
) -> list[str]:
    """Return human-readable failures for ``metric >= min`` gates and optional regressions."""
    failures = [
        f"{key}={result.metrics.get(key, 0.0):.3f} < {minimum}"
        for key, minimum in gates.items()
        if result.metrics.get(key, 0.0) < minimum
    ]
    if baseline is not None and max_drop is not None:
        for key in gates:
            before, after = baseline.metrics.get(key), result.metrics.get(key)
            if before is not None and after is not None and before - after > max_drop:
                failures.append(f"{key} regressed {before:.3f} -> {after:.3f}")
    return failures
