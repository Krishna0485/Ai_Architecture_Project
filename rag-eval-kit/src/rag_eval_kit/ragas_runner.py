"""Optional RAGAS adapter (``pip install rag-eval-kit[ragas]``).

Converts rag-eval-kit rows to a RAGAS dataset. You supply the judge LLM and embeddings objects
(LangChain-compatible) so any provider works. Returns None when RAGAS is not installed.
"""

from __future__ import annotations

from typing import Any


def to_ragas_rows(
    dataset: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {p["id"]: p for p in predictions}
    rows = []
    for item in dataset:
        pred = by_id.get(item["id"])
        if pred is None or item.get("reference_answer") is None or pred.get("abstained"):
            continue
        rows.append(
            {
                "question": item["question"],
                "answer": pred.get("answer", ""),
                "contexts": list(pred.get("contexts", [])),
                "ground_truth": item["reference_answer"],
            }
        )
    return rows


def run_ragas(
    dataset: list[dict[str, Any]], predictions: list[dict[str, Any]], llm: Any, embeddings: Any
) -> dict[str, float] | None:  # pragma: no cover - optional extra
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError:
        return None
    ds = Dataset.from_list(to_ragas_rows(dataset, predictions))
    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=llm,
        embeddings=embeddings,
    )
    return {k: float(v) for k, v in result.items()}
