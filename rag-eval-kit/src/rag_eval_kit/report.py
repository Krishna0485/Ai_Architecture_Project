"""Markdown and self-contained HTML reports (stdlib only, values HTML-escaped)."""

from __future__ import annotations

import html
from collections.abc import Sequence

from rag_eval_kit.runner import EvalResult

DEFAULT_COLUMNS = (
    "hit_at_5",
    "mrr",
    "ndcg_at_5",
    "context_precision",
    "faithfulness",
    "answer_relevancy",
    "abstention_accuracy",
    "p95_latency_ms",
    "cost_per_1k_usd",
)


def markdown_table(results: Sequence[EvalResult], columns: Sequence[str] = DEFAULT_COLUMNS) -> str:
    head = "| run | " + " | ".join(columns) + " |"
    sep = "|---" * (len(columns) + 1) + "|"
    rows = [
        f"| {r.name} | " + " | ".join(f"{r.metrics.get(c, 0.0):.3f}" for c in columns) + " |"
        for r in results
    ]
    return "\n".join([head, sep, *rows]) + "\n"


def html_report(
    results: Sequence[EvalResult],
    title: str = "RAG evaluation",
    columns: Sequence[str] = DEFAULT_COLUMNS,
    worst_n: int = 20,
) -> str:
    esc = html.escape
    th = "".join(f"<th>{esc(c)}</th>" for c in columns)
    body = "".join(
        f"<tr><td>{esc(r.name)}</td>"
        + "".join(f"<td class=n>{r.metrics.get(c, 0.0):.3f}</td>" for c in columns)
        + "</tr>"
        for r in results
    )
    sections = [f"<h2>Comparison</h2><table><tr><th>run</th>{th}</tr>{body}</table>"]
    for r in results:
        bad = sorted(
            (
                x
                for x in r.rows
                if not x["abstention_correct"] or (x["answerable"] and x.get("mrr", 1.0) < 0.5)
            ),
            key=lambda x: (x.get("mrr", 0.0), x.get("faithfulness", 0.0)),
        )[:worst_n]
        if bad:
            trs = "".join(
                f"<tr><td>{esc(str(x['id']))}</td><td>{esc(', '.join(x['tags']))}</td>"
                f"<td class=n>{x.get('mrr', 0):.2f}</td>"
                f"<td>{'abstained' if x['abstained'] else 'answered'}</td></tr>"
                for x in bad
            )
            sections.append(
                f"<h2>Worst items - {esc(r.name)}</h2><table><tr><th>id</th>"
                f"<th>tags</th><th>mrr</th><th>behaviour</th></tr>{trs}</table>"
            )
        if r.missing_predictions:
            sections.append(
                f"<p class=w>{esc(r.name)}: {len(r.missing_predictions)} items had "
                "no prediction (scored as abstentions)</p>"
            )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)}</title>
<style>:root{{--bg:#fbfaf7;--fg:#1d1d1b;--line:#e3e0d8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--line:#34332f}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;max-width:1100px;
margin:0 auto;padding:24px 16px}}table{{border-collapse:collapse;width:100%;display:block;
overflow-x:auto}}th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}.w{{color:#b3261e}}</style></head>
<body><h1>{esc(title)}</h1>{"".join(sections)}</body></html>"""
