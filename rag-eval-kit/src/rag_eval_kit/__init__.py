"""rag-eval-kit: reproducible RAG evaluation."""

from rag_eval_kit.metrics import (
    answer_f1,
    answer_relevancy,
    average_precision,
    faithfulness,
    hit_at_k,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from rag_eval_kit.runner import EvalResult, evaluate, load_jsonl

__version__ = "0.1.0"
__all__ = [
    "EvalResult",
    "answer_f1",
    "answer_relevancy",
    "average_precision",
    "evaluate",
    "faithfulness",
    "hit_at_k",
    "load_jsonl",
    "mean",
    "ndcg_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
