"""Performance benchmarks: latency, throughput, tokens/request, cache hit rate, estimated cost.

    python benchmarks/run_bench.py                       # offline (heuristic provider)
    python benchmarks/run_bench.py --requests 400 --concurrency 8
    REGINTEL_LLM_PROVIDER=openai_compatible python benchmarks/run_bench.py \
        --quant-models smart,smart-q8,smart-fp16   # LiteLLM aliases in infra/litellm.yaml

Workload: questions drawn from the golden set with a Zipf-like distribution (popular questions
repeat, as in real help-desk traffic), so cache effects are measurable. Cost is *estimated* from
token counts x the pricing table in Settings.pricing (USD per 1M tokens) - see docs/benchmarks.md.
Results: benchmarks/results/<date>.json, <date>.md and latest.md.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regintel.config import Settings  # noqa: E402
from regintel.container import build_container  # noqa: E402
from regintel.ingestion.pipeline import ingest_directory  # noqa: E402
from regintel.llm.base import LLMRequest, LLMResponse  # noqa: E402
from regintel.retrieval.base import SecurityContext  # noqa: E402
from regintel.retrieval.factory import NAMED_CONFIGS  # noqa: E402

CTX = SecurityContext("acme", ("compliance",), "bench")
RESULTS = ROOT / "benchmarks" / "results"


@dataclass(frozen=True)
class BenchConfig:
    name: str
    description: str
    overrides: dict[str, Any]
    retrieval: str = "hybrid_rerank_rewrite"


CONFIGS = [
    BenchConfig(
        "baseline",
        "no cache, no compression, single model",
        {"cache_backend": "none", "use_context_compression": False, "routing_enabled": False},
    ),
    BenchConfig(
        "+compression",
        "context compressed to token budget",
        {"cache_backend": "none", "use_context_compression": True, "routing_enabled": False},
    ),
    BenchConfig(
        "+routing",
        "fast model for rewrite, smart for answers",
        {"cache_backend": "none", "use_context_compression": True, "routing_enabled": True},
    ),
    BenchConfig(
        "+semantic_cache",
        "compression + routing + semantic/exact cache",
        {"cache_backend": "memory", "use_context_compression": True, "routing_enabled": True},
    ),
]


def workload(n: int, seed: int) -> list[str]:
    items = [
        json.loads(line)
        for line in (ROOT / "evals/datasets/golden_qa.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    questions = [i["question"] for i in items if i["answerable"]]
    rng = random.Random(seed)
    weights = [1 / (rank + 1) ** 1.1 for rank in range(len(questions))]
    rng.shuffle(questions)
    return rng.choices(questions, weights=weights, k=n)


def run(
    cfg: BenchConfig,
    questions: list[str],
    concurrency: int,
    chunks: list[Any],
    model_override: str | None = None,
) -> dict[str, Any]:
    settings = Settings(audit_backend="memory", **cfg.overrides)
    container = build_container(
        settings, chunks=chunks, retrieval_config=NAMED_CONFIGS[cfg.retrieval]
    )
    if model_override:
        container.gateway.routing.smart_model = model_override
        container.gateway.routing.fast_model = model_override
    calls: list[LLMResponse] = []
    lock = threading.Lock()
    original: Callable[[LLMRequest], LLMResponse] = container.gateway.complete

    def counting(req: LLMRequest) -> LLMResponse:
        resp = original(req)
        with lock:
            calls.append(resp)
        return resp

    container.gateway.complete = counting  # type: ignore[method-assign]
    latencies: list[float] = []
    cached = 0

    def one(q: str) -> None:
        nonlocal cached
        t0 = time.perf_counter()
        ans = container.answers.answer(q, CTX)
        dt = (time.perf_counter() - t0) * 1000
        with lock:
            latencies.append(dt)
            cached += int(ans.cached)

    for q in questions[:3]:  # warm-up (imports, JIT-y caches) excluded from timing
        container.answers.retrieval.search(q, CTX)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, questions))
    wall = time.perf_counter() - start
    lat = sorted(latencies)
    tokens = sum(r.usage.total for r in calls if not r.cached)
    cost = sum(r.cost_usd for r in calls)
    n = len(questions)
    return {
        "config": cfg.name,
        "description": cfg.description,
        "requests": n,
        "concurrency": concurrency,
        "model": model_override or settings.llm_provider,
        "p50_ms": round(statistics.median(lat), 2),
        "p95_ms": round(lat[min(n - 1, int(0.95 * n))], 2),
        "throughput_rps": round(n / wall, 2),
        "llm_calls": len(calls),
        "tokens_per_request": round(tokens / n, 1),
        "answer_cache_hit_rate": round(cached / n, 4),
        "est_cost_per_1k_usd": round(cost / n * 1000, 4),
    }


def markdown(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [
        "| Configuration | p50 | p95 | Throughput | LLM calls | Tokens/req | Cache hit | "
        "Est. cost / 1K req |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['config']} | {r['p50_ms']:.1f} ms | {r['p95_ms']:.1f} ms | "
            f"{r['throughput_rps']:.1f} rps | {r['llm_calls']} | {r['tokens_per_request']:.0f} | "
            f"{r['answer_cache_hit_rate']:.0%} | ${r['est_cost_per_1k_usd']:.2f} |"
        )
    lines += [
        "",
        f"{meta['requests']} requests, concurrency {meta['concurrency']}, provider "
        f"`{meta['provider']}`, pricing (USD/1M in,out) {meta['pricing']}. Generated "
        f"{meta['generated_at']} by `make bench`.",
    ]
    if meta["provider"] == "heuristic":
        lines.append(
            "Latency reflects retrieval + orchestration only (offline deterministic "
            "model); token counts and cost are computed from real prompt sizes."
        )
    if meta.get("quantization"):
        lines += [
            "",
            "| Local model (quantisation) | p50 | p95 | Throughput |",
            "|---|---|---|---|",
        ]
        for r in meta["quantization"]:
            lines.append(
                f"| {r['model']} | {r['p50_ms']:.0f} ms | {r['p95_ms']:.0f} ms | "
                f"{r['throughput_rps']:.2f} rps |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--quant-models", default="", help="comma-separated gateway model names")
    args = ap.parse_args(argv)
    chunks = ingest_directory(ROOT / "data/samples")
    questions = workload(args.requests, args.seed)
    results = []
    for cfg in CONFIGS:
        res = run(cfg, questions, args.concurrency, chunks)
        results.append(res)
        print(json.dumps(res))
    settings = Settings()
    meta: dict[str, Any] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requests": args.requests,
        "concurrency": args.concurrency,
        "provider": settings.llm_provider,
        "pricing": settings.pricing,
    }
    if args.quant_models:
        if settings.llm_provider == "heuristic":
            print("skipping quantisation comparison: needs REGINTEL_LLM_PROVIDER=openai_compatible")
        else:  # pragma: no cover - needs Ollama via LiteLLM
            q = questions[: min(60, len(questions))]
            meta["quantization"] = [
                run(CONFIGS[2], q, 1, chunks, m) for m in args.quant_models.split(",")
            ]
    RESULTS.mkdir(parents=True, exist_ok=True)
    date = meta["generated_at"][:10]
    payload = {"meta": meta, "results": results}
    (RESULTS / f"{date}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = markdown(results, meta)
    (RESULTS / f"{date}.md").write_text(md, encoding="utf-8")
    (RESULTS / "latest.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
