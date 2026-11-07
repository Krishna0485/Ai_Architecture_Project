"""LLM-as-judge (prompts/judge.v1.md) through the gateway. Scores 1-5, normalised to 0-1.

Calibration: before trusting a judge model, score a hand-labelled sample and report agreement
(see docs/evaluation.md#judge-calibration). In lite mode the heuristic provider grades by token F1.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from regintel.generation.prompts import PromptRegistry
from regintel.guardrails import OutputValidationError, parse_structured
from regintel.llm.base import LLMError, LLMRequest
from regintel.llm.gateway import LLMGateway


class JudgeScore(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = ""


def judge(
    gateway: LLMGateway, prompts: PromptRegistry, question: str, answer: str, reference: str
) -> float | None:
    system, user = prompts.render("judge.v1", question=question, answer=answer, reference=reference)
    try:
        resp = gateway.complete(
            LLMRequest(
                task="judge",
                prompt_id="judge.v1",
                system=system,
                user=user,
                json_mode=True,
                inputs={"question": question, "answer": answer, "reference": reference},
                max_tokens=150,
            )
        )
        return (parse_structured(resp.text, JudgeScore).score - 1) / 4
    except (LLMError, OutputValidationError):
        return None
