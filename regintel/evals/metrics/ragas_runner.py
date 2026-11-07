"""Optional RAGAS evaluation (``uv sync --group eval``) using an LLM judge via the LiteLLM gateway.

RAGAS needs a judge LLM + embeddings. We point its OpenAI-compatible client at the gateway so the
judge goes through the same routing/budgets. Skipped (returns None) when unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def run_ragas(
    rows: list[dict[str, Any]], gateway_url: str, api_key: str | None, judge_model: str = "smart"
) -> dict[str, float] | None:  # pragma: no cover
    try:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError as exc:
        log.warning("RAGAS unavailable (%s); using lexical proxies only", exc)
        return None
    llm = ChatOpenAI(
        base_url=f"{gateway_url}/v1", api_key=api_key or "none", model=judge_model, temperature=0
    )
    emb = OpenAIEmbeddings(base_url=f"{gateway_url}/v1", api_key=api_key or "none", model="embed")
    ds = Dataset.from_list(
        [
            {
                "question": r["question"],
                "answer": r["answer"],
                "contexts": r["contexts"],
                "ground_truth": r["reference"] or "",
            }
            for r in rows
            if r.get("reference")
        ]
    )
    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=llm,
        embeddings=emb,
    )
    return {k: float(v) for k, v in result.items()}
