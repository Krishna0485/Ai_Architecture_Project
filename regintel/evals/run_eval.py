"""RegIntel evaluation runner.

    python evals/run_eval.py --dataset evals/datasets/golden_qa.jsonl            # full
    python evals/run_eval.py --subset 30 --configs hybrid_rerank                  # CI fast gate
    python evals/run_eval.py --suites retrieval,checks,chunking --judge

Writes evals/reports/summary.json, evals/reports/eval-<date>.html, evals/reports/latest.html and
evals/reports/comparison.md. Exits 1 when a gate in evals/thresholds.yaml fails.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.metrics import generation as gm  # noqa: E402
from evals.metrics import retrieval as rm  # noqa: E402
from evals.metrics.judge import judge  # noqa: E402
from regintel.agents.models import ReviewDecision  # noqa: E402
from regintel.config import Settings  # noqa: E402
from regintel.container import Container, build_container  # noqa: E402
from regintel.generation.answer import AnswerService  # noqa: E402
from regintel.ingestion.chunker import FixedSizeChunker, StructureAwareChunker  # noqa: E402
from regintel.ingestion.pipeline import ingest_directory  # noqa: E402
from regintel.retrieval.base import SecurityContext  # noqa: E402
from regintel.retrieval.factory import NAMED_CONFIGS, RetrievalConfig  # noqa: E402

REPORTS = ROOT / "evals" / "reports"
EVAL_CTX = SecurityContext("acme", ("compliance",), "eval-runner")
METRIC_KEYS = [
    "hit_at_5",
    "recall_at_10",
    "mrr",
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
    "answer_f1",
    "citation_precision",
    "abstention_accuracy",
    "false_abstention_rate",
]


def load_dataset(path: Path, subset: int | None, seed: int = 7) -> list[dict[str, Any]]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if subset and subset < len(items):
        rng = random.Random(seed)
        answerable = [i for i in items if i["answerable"]]
        unanswerable = [i for i in items if not i["answerable"]]
        n_un = max(1, round(subset * len(unanswerable) / len(items)))
        items = rng.sample(answerable, subset - n_un) + rng.sample(unanswerable, n_un)
    return items


def eval_settings() -> Settings:
    # Hermetic: no caches (every question is computed), in-memory audit, inline agents.
    return Settings(cache_backend="none", audit_backend="memory", check_executor="inline")


def _sec(chunk_id: str, container: Container) -> str:
    c = container.chunks.get(chunk_id)
    return f"{c.metadata['source']}:{c.section_id}" if c else ""


def run_config(
    container: Container,
    name: str,
    cfg: RetrievalConfig,
    items: list[dict[str, Any]],
    use_judge: bool,
) -> dict[str, Any]:
    pipeline = container.retrieval.with_config(cfg)
    svc = AnswerService(
        pipeline,
        container.gateway,
        container.prompts,
        container.redactor,
        container.scanner,
        min_score=container.settings.min_score,
        context_budget=container.settings.context_token_budget,
        compress=container.settings.use_context_compression,
        allowed_link_domains=container.settings.allowed_link_domains,
        idf=pipeline.term_weight,
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        relevant = set(item["relevant_sections"])
        t0 = time.perf_counter()
        ranked = pipeline.search_k(item["question"], EVAL_CTX, 10)
        retrieval_ms = (time.perf_counter() - t0) * 1000
        ranked_secs = [f"{h.chunk.metadata['source']}:{h.chunk.section_id}" for h in ranked]
        t1 = time.perf_counter()
        ans = svc.answer(item["question"], EVAL_CTX)
        answer_ms = (time.perf_counter() - t1) * 1000
        ctx_secs = [_sec(cid, container) for cid in ans.retrieved_ids]
        cited = [c.chunk_id for c in ans.citations]
        cited_texts = [container.chunks.get(c).text for c in cited if container.chunks.get(c)]
        row: dict[str, Any] = {
            "id": item["id"],
            "question": item["question"],
            "tags": item["tags"],
            "answerable": item["answerable"],
            "answer": ans.answer,
            "abstained": ans.abstained,
            "reference": item["reference_answer"],
            "relevant": sorted(relevant),
            "retrieved": ranked_secs[:5],
            "cited_sections": [_sec(c, container) for c in cited],
            "retrieval_ms": retrieval_ms,
            "answer_ms": answer_ms,
            "contexts": [
                container.chunks.get(c).text
                for c in ans.retrieved_ids  # type: ignore[union-attr]
                if container.chunks.get(c)
            ],
        }
        if item["answerable"]:
            row |= {
                "hit_at_5": rm.hit_at_k(ranked_secs, relevant, 5),
                "recall_at_10": rm.recall_at_k(list(dict.fromkeys(ranked_secs)), relevant, 10),
                "mrr": rm.reciprocal_rank(ranked_secs, relevant, 10),
                "context_precision": rm.average_precision(ctx_secs, relevant, 5),
                "context_recall": rm.recall_at_k(list(dict.fromkeys(ctx_secs)), relevant, 5),
                "faithfulness": 0.0 if ans.abstained else gm.faithfulness(ans.answer, cited_texts),
                "answer_relevancy": 0.0
                if ans.abstained
                else gm.answer_relevancy(item["question"], ans.answer),
                "answer_f1": 0.0
                if ans.abstained
                else gm.answer_f1(ans.answer, item["reference_answer"]),
                "citation_precision": (
                    sum(s in relevant for s in row["cited_sections"]) / len(cited)
                )
                if cited
                else 0.0,
                "abstention_correct": not ans.abstained,
            }
            if use_judge and not ans.abstained:
                row["judge"] = judge(
                    container.gateway,
                    container.prompts,
                    item["question"],
                    ans.answer,
                    item["reference_answer"],
                )
        else:
            row["abstention_correct"] = ans.abstained
        rows.append(row)
    ans_rows = [r for r in rows if r["answerable"]]
    answered = [r for r in ans_rows if not r["abstained"]]
    metrics: dict[str, float] = {
        k: rm.mean([r[k] for r in ans_rows])
        for k in (
            "hit_at_5",
            "recall_at_10",
            "mrr",
            "context_precision",
            "context_recall",
            "citation_precision",
        )
    }
    # Generation quality is measured on answered questions; abstention is measured separately.
    for k in ("faithfulness", "answer_relevancy", "answer_f1"):
        metrics[k] = rm.mean([r[k] for r in answered])
    metrics["abstention_accuracy"] = rm.mean([float(r["abstention_correct"]) for r in rows])
    metrics["false_abstention_rate"] = rm.mean([float(r["abstained"]) for r in ans_rows])
    judged = [r["judge"] for r in ans_rows if r.get("judge") is not None]
    if judged:
        metrics["judge_score"] = rm.mean(judged)
    lat = sorted(r["retrieval_ms"] + r["answer_ms"] for r in rows)
    metrics["p50_latency_ms"] = statistics.median(lat)
    metrics["p95_latency_ms"] = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    return {
        "name": name,
        "config": cfg.key,
        "metrics": {k: round(v, 4) for k, v in metrics.items()},
        "rows": rows,
    }


def per_tag(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    tags: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["answerable"]:
            for t in r["tags"]:
                tags.setdefault(t, []).append(r)
    return {
        t: {
            "n": len(rs),
            "hit_at_5": round(rm.mean([r["hit_at_5"] for r in rs]), 3),
            "mrr": round(rm.mean([r["mrr"] for r in rs]), 3),
            "faithfulness": round(
                rm.mean([r["faithfulness"] for r in rs if not r["abstained"]]), 3
            ),
        }
        for t, rs in sorted(tags.items())
    }


def worst(rows: list[dict[str, Any]], n: int = 20) -> list[dict[str, Any]]:
    def badness(r: dict[str, Any]) -> tuple[float, ...]:
        if not r["answerable"]:
            return (0.0 if not r["abstention_correct"] else 9.0,)
        return (r["hit_at_5"] + r["mrr"], r.get("faithfulness", 0), r.get("answer_f1", 0))

    failing = [
        r
        for r in rows
        if not r["abstention_correct"]
        or (r["answerable"] and (r["hit_at_5"] < 1 or r["faithfulness"] < 0.9 or r["mrr"] < 0.5))
    ]
    return sorted(failing, key=badness)[:n]


def eval_checks(container: Container) -> dict[str, Any]:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/datasets/check_cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    tp = fp = fn = 0
    results = []
    for case in cases:
        text = (ROOT / "data/synthetic" / case["document"]).read_text(encoding="utf-8")
        doc = container.documents.add(
            EVAL_CTX.tenant_id, case["document"], container.redactor.redact(text).text
        )
        t0 = time.perf_counter()
        view = container.checks.start(doc.id, EVAL_CTX)
        view = container.checks.get(view.check_id, EVAL_CTX)
        found = {f["requirement_id"] for f in view.findings if f["status"] != "compliant"}
        if view.status == "awaiting_review":
            container.checks.review(view.check_id, ReviewDecision(decision="approve"), EVAL_CTX)
        state = container.checks.graph.get_state(container.checks._config(view.check_id)).values
        expected = set(case["expected_gaps"])
        tp += len(found & expected)
        fp += len(found - expected)
        fn += len(expected - found)
        results.append(
            {
                "id": case["id"],
                "doc_type": state.get("doc_type"),
                "expected": sorted(expected),
                "found": sorted(found),
                "exact": found == expected,
                "steps": state.get("steps", 0),
                "quarantined_lines": len(state.get("quarantined_lines", [])),
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )
    return {
        "metrics": {
            "check_gap_recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
            "check_gap_precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
            "check_task_success": round(rm.mean([float(r["exact"]) for r in results]), 4),
            "check_mean_steps": round(rm.mean([float(r["steps"]) for r in results]), 2),
        },
        "cases": results,
    }


def eval_chunking(items: list[dict[str, Any]]) -> dict[str, Any]:
    """ADR-0001 experiment: structure-aware vs fixed-size chunking under hybrid+rerank."""
    out = {}
    for name, chunker in (
        ("structure_aware", StructureAwareChunker()),
        ("fixed_400", FixedSizeChunker(400, 50)),
    ):
        chunks = ingest_directory(ROOT / "data/samples", chunker)
        c = build_container(eval_settings(), chunks=chunks)
        res = run_config(c, name, NAMED_CONFIGS["hybrid_rerank"], items, False)
        out[name] = {
            "chunks": len(chunks),
            **{
                k: res["metrics"][k]
                for k in ("hit_at_5", "mrr", "faithfulness", "citation_precision")
            },
        }
    return out


def check_gates(
    summary: dict[str, Any], thresholds: dict[str, Any], previous: dict[str, Any] | None
) -> list[str]:
    failures: list[str] = []
    gate_name = thresholds.get("gate_config", "hybrid_rerank")
    configs = {c["name"]: c["metrics"] for c in summary["configs"]}
    metrics = dict(configs.get(gate_name, {}))
    metrics |= summary.get("checks", {}).get("metrics", {})
    for key, rule in thresholds.get("gates", {}).items():
        if key == "regression" or key not in metrics:
            continue
        if "min" in rule and metrics[key] < rule["min"]:
            failures.append(f"{gate_name}.{key} = {metrics[key]:.3f} < min {rule['min']}")
    reg = thresholds.get("gates", {}).get("regression", {})
    if previous and summary["dataset"]["fingerprint"] == previous.get("dataset", {}).get(
        "fingerprint"
    ):
        prev = {c["name"]: c["metrics"] for c in previous.get("configs", [])}.get(gate_name, {})
        for key, metric in (
            ("max_drop_hit_at_5", "hit_at_5"),
            ("max_drop_faithfulness", "faithfulness"),
        ):
            if (
                key in reg
                and metric in prev
                and metric in metrics
                and prev[metric] - metrics[metric] > reg[key]
            ):
                failures.append(
                    f"regression: {metric} dropped {prev[metric]:.3f} -> "
                    f"{metrics[metric]:.3f} (> {reg[key]})"
                )
    return failures


def comparison_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "| Configuration | hit@5 | recall@10 | MRR | Context precision | Faithfulness* | "
        "Answer relevancy* | Citation precision | Abstention acc. | p95 latency |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in summary["configs"]:
        m = c["metrics"]
        lines.append(
            f"| {c['config']} | {m['hit_at_5']:.2f} | {m['recall_at_10']:.2f} | {m['mrr']:.2f} | "
            f"{m['context_precision']:.2f} | {m['faithfulness']:.2f} | {m['answer_relevancy']:.2f} "
            f"| {m['citation_precision']:.2f} | {m['abstention_accuracy']:.2f} | "
            f"{m['p95_latency_ms']:.0f} ms |"
        )
    ds = summary["dataset"]
    lines.append("")
    lines.append(
        f"Dataset: {ds['name']} v{ds['version']}, {ds['items']} questions "
        f"({ds['answerable']} answerable). LLM provider: {summary['env']['llm_provider']}. "
        f"*Lexical proxy metrics (see docs/evaluation.md). Generated {summary['generated_at']}"
        f" by `make eval`."
    )
    if "checks" in summary:
        m = summary["checks"]["metrics"]
        lines += [
            "",
            "| Agent check suite | Gap recall | Gap precision | Task success | Mean steps |",
            "|---|---|---|---|---|",
            f"| compliance_check ({len(summary['checks']['cases'])} synthetic docs) | "
            f"{m['check_gap_recall']:.2f} | {m['check_gap_precision']:.2f} | "
            f"{m['check_task_success']:.2f} | {m['check_mean_steps']:.1f} |",
        ]
    if "chunking" in summary:
        lines += [
            "",
            "| Chunking (hybrid+rerank) | chunks | hit@5 | MRR | Faithfulness* | "
            "Citation precision |",
            "|---|---|---|---|---|---|",
        ]
        for name, m in summary["chunking"].items():
            lines.append(
                f"| {name} | {m['chunks']} | {m['hit_at_5']:.2f} | {m['mrr']:.2f} | "
                f"{m['faithfulness']:.2f} | {m['citation_precision']:.2f} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "evals/datasets/golden_qa.jsonl")
    ap.add_argument("--configs", default=",".join(NAMED_CONFIGS))
    ap.add_argument("--suites", default="retrieval,checks,chunking")
    ap.add_argument("--subset", type=int, default=None)
    ap.add_argument("--judge", action="store_true", help="add LLM-as-judge scores")
    ap.add_argument("--out", type=Path, default=REPORTS)
    ap.add_argument("--no-gate", action="store_true")
    args = ap.parse_args(argv)

    thresholds = yaml.safe_load((ROOT / "evals/thresholds.yaml").read_text(encoding="utf-8"))
    subset = args.subset
    items = load_dataset(args.dataset, subset)
    suites = set(args.suites.split(","))
    settings = eval_settings()
    container = build_container(settings, chunks=ingest_directory(ROOT / "data/samples"))
    raw = args.dataset.read_bytes()
    import hashlib

    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": {
            "name": args.dataset.stem,
            "version": "1.0",
            "items": len(items),
            "answerable": sum(i["answerable"] for i in items),
            "subset": subset,
            "fingerprint": hashlib.sha256(raw).hexdigest()[:12] + (f"-s{subset}" if subset else ""),
        },
        "env": {
            "llm_provider": settings.llm_provider,
            "embedder": settings.embedder,
            "reranker": settings.reranker,
            "chunks": len(container.chunks),
            "python": platform.python_version(),
            "min_score": settings.min_score,
        },
        "configs": [],
    }
    rows_by_config: dict[str, list[dict[str, Any]]] = {}
    if "retrieval" in suites:
        for name in args.configs.split(","):
            res = run_config(container, name, NAMED_CONFIGS[name], items, args.judge)
            rows_by_config[name] = res.pop("rows")
            summary["configs"].append(res)
            print(
                f"{name:24s} "
                + " ".join(
                    f"{k}={res['metrics'][k]:.3f}"
                    for k in (
                        "hit_at_5",
                        "mrr",
                        "faithfulness",
                        "answer_relevancy",
                        "abstention_accuracy",
                    )
                )
            )
    gate = thresholds.get("gate_config", "hybrid_rerank")
    gate_rows = rows_by_config.get(gate) or next(iter(rows_by_config.values()), [])
    if gate_rows:
        summary["per_tag"] = per_tag(gate_rows)
        summary["worst"] = [
            {
                k: r.get(k)
                for k in (
                    "id",
                    "question",
                    "tags",
                    "answer",
                    "relevant",
                    "retrieved",
                    "hit_at_5",
                    "mrr",
                    "faithfulness",
                    "abstained",
                    "answerable",
                )
            }
            for r in worst(gate_rows)
        ]
    if "checks" in suites:
        summary["checks"] = eval_checks(container)
        print("checks", summary["checks"]["metrics"])
    if "chunking" in suites:
        summary["chunking"] = eval_chunking(items)
        print("chunking", summary["chunking"])

    args.out.mkdir(parents=True, exist_ok=True)
    summary_path = args.out / ("summary.json" if not subset else "summary_subset.json")
    previous = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    )
    failures = check_gates(summary, thresholds, previous)
    summary["gate"] = {"config": gate, "passed": not failures, "failures": failures}
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not subset:
        (args.out / "comparison.md").write_text(comparison_markdown(summary), encoding="utf-8")
        env = Environment(loader=FileSystemLoader(ROOT / "evals"), autoescape=select_autoescape())
        html = env.get_template("report_template.html.j2").render(s=summary, keys=METRIC_KEYS)
        date = summary["generated_at"][:10]
        (args.out / f"eval-{date}.html").write_text(html, encoding="utf-8")
        (args.out / "latest.html").write_text(html, encoding="utf-8")
    print(f"gate[{gate}]: {'PASS' if not failures else 'FAIL'}")
    for f in failures:
        print("  -", f)
    return 0 if (not failures or args.no_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
