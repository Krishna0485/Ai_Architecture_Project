"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from regintel.api.auth import resolve_api_key
from regintel.container import Container
from regintel.guardrails import PolicyDeniedError
from regintel.retrieval.base import SecurityContext


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_security_context(
    request: Request,
    container: ContainerDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> SecurityContext:
    ctx = resolve_api_key(
        x_api_key, container.settings.api_keys, getattr(request.state, "request_id", "")
    )
    if ctx is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return ctx


CtxDep = Annotated[SecurityContext, Depends(get_security_context)]


def authorize(container: Container, ctx: SecurityContext, action: str) -> None:
    try:
        container.policy.authorize(ctx, action)
    except PolicyDeniedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
