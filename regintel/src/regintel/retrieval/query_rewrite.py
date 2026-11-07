"""LLM query rewriting (routed to the fast model, cached by the gateway's exact cache)."""

from __future__ import annotations

from regintel.generation.prompts import PromptRegistry
from regintel.llm.base import LLMError, LLMRequest
from regintel.llm.gateway import LLMGateway

PROMPT_ID = "query_rewrite.v1"


class QueryRewriter:
    def __init__(self, gateway: LLMGateway, prompts: PromptRegistry) -> None:
        self.gateway = gateway
        self.prompts = prompts

    def rewrite(self, question: str, tenant_id: str = "public") -> str:
        system, user = self.prompts.render(PROMPT_ID, question=question)
        try:
            resp = self.gateway.complete(
                LLMRequest(
                    task="query_rewrite",
                    prompt_id=PROMPT_ID,
                    system=system,
                    user=user,
                    inputs={"question": question},
                    max_tokens=120,
                    tenant_id=tenant_id,
                )
            )
        except LLMError:
            return question  # rewriting is an optimisation; never fail the request over it
        rewritten = resp.text.strip().splitlines()[0] if resp.text.strip() else ""
        # Guard against a model that drops the original intent: keep the original terms.
        return rewritten if question.lower() in rewritten.lower() else f"{question} {rewritten}"
