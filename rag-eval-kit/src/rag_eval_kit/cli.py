"""``rag-eval`` command line.

rag-eval run --dataset ds.jsonl --predictions run_a.jsonl [--predictions run_b.jsonl ...]
             [--k 5] [--out report/] [--gate hit_at_5=0.8 --gate mrr=0.6]
             [--baseline report/summary.json --max-drop 0.03]
rag-eval calibrate --labels labels.jsonl        # {"human": 1-5, "judge": 1-5} per line
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_eval_kit.judge import calibrate
from rag_eval_kit.report import html_report, markdown_table
from rag_eval_kit.runner import EvalResult, check_gates, evaluate, load_jsonl


def _gate(spec: str) -> tuple[str, float]:
    key, _, value = spec.partition("=")
    if not key or not value:
        raise argparse.ArgumentTypeError(f"gate must look like metric=0.8, got {spec!r}")
    return key, float(value)


def cmd_run(args: argparse.Namespace) -> int:
    dataset = load_jsonl(args.dataset)
    results = [
        evaluate(dataset, load_jsonl(p), k=args.k, name=Path(p).stem) for p in args.predictions
    ]
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8"
    )
    (out / "comparison.md").write_text(markdown_table(results), encoding="utf-8")
    (out / "report.html").write_text(html_report(results), encoding="utf-8")
    print(markdown_table(results))
    baseline = None
    if args.baseline:
        prev = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        baseline = EvalResult(prev[0]["name"], prev[0]["metrics"])
    failures = check_gates(results[0], dict(args.gate or []), baseline, args.max_drop)
    for f in failures:
        print(f"GATE FAIL: {f}", file=sys.stderr)
    return 1 if failures else 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    rows = load_jsonl(args.labels)
    cal = calibrate([int(r["human"]) for r in rows], [int(r["judge"]) for r in rows])
    print(json.dumps(cal.__dict__, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rag-eval", description="Benchmark RAG pipelines.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="score one or more prediction files")
    run.add_argument("--dataset", required=True, type=Path)
    run.add_argument("--predictions", required=True, action="append")
    run.add_argument("--k", type=int, default=5)
    run.add_argument("--out", type=Path, default=Path("rag-eval-report"))
    run.add_argument("--gate", type=_gate, action="append", help="metric=minimum (first run)")
    run.add_argument("--baseline", help="previous summary.json for regression checks")
    run.add_argument("--max-drop", type=float, default=None)
    run.set_defaults(fn=cmd_run)
    cal = sub.add_parser("calibrate", help="judge vs human agreement")
    cal.add_argument("--labels", required=True, type=Path)
    cal.set_defaults(fn=cmd_calibrate)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
