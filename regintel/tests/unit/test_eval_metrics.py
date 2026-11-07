"""Evaluation metrics checked against hand-computed examples."""

from __future__ import annotations

import pytest

from evals.metrics import generation as gm
from evals.metrics import retrieval as rm
from evals.run_eval import check_gates, comparison_markdown, load_dataset, per_tag, worst
from regintel.config import PROJECT_ROOT

RANKED = ["x", "a", "y", "b", "z"]
REL = {"a", "b"}


def test_hit_recall_mrr_ap() -> None:
    assert rm.hit_at_k(RANKED, REL, 1) == 0.0
    assert rm.hit_at_k(RANKED, REL, 2) == 1.0
    assert rm.recall_at_k(RANKED, REL, 2) == 0.5
    assert rm.recall_at_k(RANKED, REL, 5) == 1.0
    assert rm.recall_at_k(RANKED, set(), 5) == 0.0
    assert rm.reciprocal_rank(RANKED, REL) == 0.5
    assert rm.reciprocal_rank(RANKED, REL, k=1) == 0.0
    # AP@5: relevant at ranks 2 and 4 -> (1/2 + 2/4) / 2 = 0.5
    assert rm.average_precision(RANKED, REL, 5) == pytest.approx(0.5)
    assert rm.average_precision(["x"], REL, 5) == 0.0
    assert rm.mean([]) == 0.0


def test_generation_proxies() -> None:
    ctx = ["Employers must provide 12 workweeks of leave in a 12-month period."]
    assert gm.faithfulness("Employers must provide 12 workweeks of leave [1].", ctx) == 1.0
    assert gm.faithfulness("Bananas are yellow and tasty fruit.", ctx) == 0.0
    assert gm.faithfulness("anything", []) == 0.0
    assert gm.answer_relevancy("How many workweeks of leave?", "12 workweeks of leave") == 1.0
    assert gm.answer_relevancy("the of", "x") == 0.0
    assert gm.answer_f1("12 workweeks [1]", "12 workweeks") == 1.0


def test_dataset_subset_is_stratified_and_deterministic() -> None:
    path = PROJECT_ROOT / "evals/datasets/golden_qa.jsonl"
    full = load_dataset(path, None)
    a, b = load_dataset(path, 30, seed=1), load_dataset(path, 30, seed=1)
    assert len(a) == 30 and [i["id"] for i in a] == [i["id"] for i in b]
    assert any(not i["answerable"] for i in a) and len(full) > 60


def _summary(hit: float) -> dict:  # type: ignore[type-arg]
    m = {
        "hit_at_5": hit,
        "recall_at_10": 1,
        "mrr": 0.9,
        "context_precision": 0.9,
        "faithfulness": 1.0,
        "answer_relevancy": 0.8,
        "citation_precision": 0.8,
        "abstention_accuracy": 1.0,
        "p95_latency_ms": 3,
    }
    return {
        "configs": [{"name": "hybrid_rerank", "config": "hybrid+rerank", "metrics": m}],
        "dataset": {"name": "g", "version": "1", "items": 3, "answerable": 2, "fingerprint": "f"},
        "env": {"llm_provider": "heuristic"},
        "generated_at": "now",
        "checks": {
            "metrics": {
                "check_gap_recall": 1.0,
                "check_gap_precision": 1.0,
                "check_task_success": 1.0,
                "check_mean_steps": 7,
            },
            "cases": [],
        },
        "chunking": {
            "s": {"chunks": 1, "hit_at_5": 1, "mrr": 1, "faithfulness": 1, "citation_precision": 1}
        },
    }


def test_gates_and_regression() -> None:
    th = {
        "gate_config": "hybrid_rerank",
        "gates": {
            "hit_at_5": {"min": 0.8},
            "check_gap_recall": {"min": 0.95},
            "regression": {"max_drop_hit_at_5": 0.03},
        },
    }
    assert check_gates(_summary(0.9), th, None) == []
    assert "hit_at_5" in check_gates(_summary(0.5), th, None)[0]
    regress = check_gates(_summary(0.85), th, _summary(0.95))
    assert regress and "regression" in regress[0]
    md = comparison_markdown(_summary(0.9))
    assert "| hybrid+rerank | 0.90 |" in md and "Agent check suite" in md


def test_per_tag_and_worst() -> None:
    rows = [
        {
            "answerable": True,
            "tags": ["t"],
            "hit_at_5": 1.0,
            "mrr": 1.0,
            "faithfulness": 1.0,
            "abstained": False,
            "abstention_correct": True,
            "answer_f1": 1,
        },
        {
            "answerable": True,
            "tags": ["t"],
            "hit_at_5": 0.0,
            "mrr": 0.0,
            "faithfulness": 0.0,
            "abstained": True,
            "abstention_correct": False,
            "answer_f1": 0,
        },
        {"answerable": False, "tags": ["u"], "abstained": False, "abstention_correct": False},
    ]
    assert per_tag(rows)["t"] == {"n": 2, "hit_at_5": 0.5, "mrr": 0.5, "faithfulness": 1.0}
    assert len(worst(rows)) == 2
