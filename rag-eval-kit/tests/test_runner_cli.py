import json
from pathlib import Path

import pytest

from rag_eval_kit.cli import main
from rag_eval_kit.judge import build_prompt, calibrate, judge, parse_score, spearman
from rag_eval_kit.ragas_runner import to_ragas_rows
from rag_eval_kit.report import html_report, markdown_table
from rag_eval_kit.runner import EvalResult, check_gates, evaluate, load_jsonl

DATASET = [
    {
        "id": "q1",
        "question": "How many workweeks of leave?",
        "reference_answer": "12 workweeks",
        "relevant_ids": ["s1"],
        "tags": ["fmla"],
    },
    {
        "id": "q2",
        "question": "Capital of France?",
        "reference_answer": None,
        "relevant_ids": [],
        "tags": ["unanswerable"],
    },
    {
        "id": "q3",
        "question": "MFA required?",
        "reference_answer": "yes for all users",
        "relevant_ids": ["s9"],
        "tags": ["glba"],
    },
]
PREDS = [
    {
        "id": "q1",
        "retrieved_ids": ["s2", "s1"],
        "answer": "12 workweeks of leave [1]",
        "contexts": ["Employees get 12 workweeks of leave."],
        "latency_ms": 100,
        "cost_usd": 0.002,
        "prompt_tokens": 90,
        "completion_tokens": 10,
    },
    {"id": "q2", "retrieved_ids": ["s5"], "answer": "", "abstained": True, "latency_ms": 20},
]


def test_evaluate_aggregates_and_handles_missing() -> None:
    res = evaluate(DATASET, PREDS, k=5, name="a")
    assert res.missing_predictions == ["q3"]
    assert res.metrics["hit_at_5"] == 0.5 and res.metrics["mrr"] == 0.25
    assert res.metrics["abstention_accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert res.metrics["faithfulness"] == 1.0
    assert res.metrics["cost_per_1k_usd"] == pytest.approx(0.6667, abs=1e-3)
    assert res.per_tag["fmla"]["hit_at_5"] == 1.0
    assert "rows" in res.to_dict(include_rows=True)


def test_gates_and_regression() -> None:
    res = evaluate(DATASET, PREDS)
    assert check_gates(res, {"hit_at_5": 0.4}) == []
    assert check_gates(res, {"hit_at_5": 0.9})
    base = EvalResult("b", {"hit_at_5": 0.9})
    assert any("regressed" in f for f in check_gates(res, {"hit_at_5": 0.1}, base, 0.05))


def test_reports_escape_html() -> None:
    res = evaluate(DATASET, PREDS, name="<script>")
    out = html_report([res])
    assert "<script>" not in out and "&lt;script&gt;" in out and "Worst items" in out
    assert markdown_table([res]).startswith("| run |")


def test_judge_and_calibration() -> None:
    assert parse_score('ok {"score": 4, "reason": "x"}') == 4
    assert parse_score("no json") is None and parse_score('{"score": 9}') is None
    assert parse_score('{"nope": 1}') is None
    assert judge(lambda p: '{"score": 5}', "q", "a", "r") == 5
    assert "Reference answer: r" in build_prompt("q", "a", "r")
    cal = calibrate([5, 4, 2, 1], [5, 3, 2, 2])
    assert cal.exact_agreement == 0.5 and cal.within_one == 1.0 and cal.spearman > 0.9
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        calibrate([], [])
    with pytest.raises(ValueError):
        spearman([1], [1])


def test_ragas_rows() -> None:
    rows = to_ragas_rows(DATASET, PREDS)
    assert len(rows) == 1 and rows[0]["ground_truth"] == "12 workweeks"


def _write(path: Path, rows: list[dict]) -> Path:  # type: ignore[type-arg]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_cli_run_and_calibrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ds = _write(tmp_path / "ds.jsonl", DATASET)
    pa = _write(tmp_path / "run_a.jsonl", PREDS)
    out = tmp_path / "rep"
    assert (
        main(
            [
                "run",
                "--dataset",
                str(ds),
                "--predictions",
                str(pa),
                "--out",
                str(out),
                "--gate",
                "hit_at_5=0.4",
            ]
        )
        == 0
    )
    assert (out / "report.html").exists() and (out / "comparison.md").exists()
    assert (
        main(
            [
                "run",
                "--dataset",
                str(ds),
                "--predictions",
                str(pa),
                "--out",
                str(out),
                "--gate",
                "hit_at_5=0.99",
                "--baseline",
                str(out / "summary.json"),
                "--max-drop",
                "0.01",
            ]
        )
        == 1
    )
    labels = _write(tmp_path / "l.jsonl", [{"human": 5, "judge": 4}, {"human": 1, "judge": 1}])
    assert main(["calibrate", "--labels", str(labels)]) == 0
    assert "spearman" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["run", "--dataset", str(ds), "--predictions", str(pa), "--gate", "bad"])


def test_load_jsonl_reports_line(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text('{"a": 1}\n{broken\n', encoding="utf-8")
    with pytest.raises(ValueError, match=":2:"):
        load_jsonl(p)
