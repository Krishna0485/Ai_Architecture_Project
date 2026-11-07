import math

import pytest

from rag_eval_kit import metrics as m

RANKED = ["x", "a", "y", "b", "z"]
REL = {"a", "b"}


def test_retrieval_metrics_hand_computed() -> None:
    assert m.hit_at_k(RANKED, REL, 1) == 0.0 and m.hit_at_k(RANKED, REL, 2) == 1.0
    assert m.recall_at_k(RANKED, REL, 2) == 0.5 and m.recall_at_k(RANKED, set(), 2) == 0.0
    assert m.precision_at_k(RANKED, REL, 4) == 0.5 and m.precision_at_k([], REL, 3) == 0.0
    assert m.reciprocal_rank(RANKED, REL) == 0.5 and m.reciprocal_rank(RANKED, REL, 1) == 0.0
    assert m.average_precision(RANKED, REL, 5) == pytest.approx((1 / 2 + 2 / 4) / 2)
    assert m.average_precision(["q"], REL, 5) == 0.0
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert m.ndcg_at_k(RANKED, REL, 5) == pytest.approx(expected)
    assert m.ndcg_at_k(["a", "a"], {"a"}, 2) == 1.0  # duplicates count once
    assert m.ndcg_at_k(RANKED, set(), 5) == 0.0


def test_generation_proxies() -> None:
    ctx = ["Employers must provide 12 workweeks of leave in a 12-month period."]
    assert m.faithfulness("Employers must provide 12 workweeks of leave [1].", ctx) == 1.0
    assert m.faithfulness("Bananas are yellow fruit.", ctx) == 0.0
    assert m.faithfulness("x", []) == 0.0 and m.faithfulness("the of", ctx) == 0.0
    assert m.answer_relevancy("How many workweeks of leave?", "12 workweeks of leave") == 1.0
    assert m.answer_relevancy("the", "x") == 0.0
    assert m.answer_f1("12 workweeks [3]", "12 workweeks") == 1.0
    assert m.answer_f1("", "x") == 0.0 and m.answer_f1("apple", "pear") == 0.0


def test_terms_and_percentile() -> None:
    assert m.terms("Employees are entitled; entitlement 825.110") == [
        "employe",
        "entitl",
        "entitl",
        "825.110",
    ]
    assert m.percentile([5, 1, 3, 2, 4], 50) == 3 and m.percentile([], 95) == 0.0
    assert m.percentile([1, 2, 3, 4, 100], 95) == 100
