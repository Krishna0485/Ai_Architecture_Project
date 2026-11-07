"""/v1/ask - cited answers (JSON and Server-Sent Events streaming)."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from regintel.api.deps import ContainerDep, CtxDep, authorize
from regintel.audit.models import AuditEvent
from regintel.generation.answer import Answer
from regintel.llm.base import BudgetExceededError, LLMError
from regintel.retrieval.base import MetadataFilter

router = APIRouter(prefix="/v1", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    jurisdiction: str | None = Field(default=None, max_length=20)
    act: str | None = Field(default=None, max_length=120)


def _filters(req: AskRequest) -> MetadataFilter | None:
    if req.jurisdiction or req.act:
        return MetadataFilter(jurisdiction=req.jurisdiction, act=req.act)
    return None


@router.post("/ask", response_model=Answer)
def ask(req: AskRequest, container: ContainerDep, ctx: CtxDep) -> Answer:
    authorize(container, ctx, "ask")
    try:
        answer = container.answers.answer(req.question, ctx, _filters(req))
    except BudgetExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "model unavailable") from exc
    container.audit.write(
        AuditEvent(
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            actor=ctx.actor,
            action="ask",
            details={
                "question": req.question,
                "abstained": answer.abstained,
                "citations": [c.chunk_id for c in answer.citations],
                "cached": answer.cached,
            },
        )
    )
    return answer


@router.post("/ask/stream")
def ask_stream(req: AskRequest, container: ContainerDep, ctx: CtxDep) -> StreamingResponse:
    authorize(container, ctx, "ask")

    def events() -> Iterator[str]:
        try:
            for event in container.answers.stream(req.question, ctx, _filters(req)):
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        except LLMError as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
