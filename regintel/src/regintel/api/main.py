"""FastAPI application."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from regintel import __version__
from regintel.api.routers import admin, ask, check
from regintel.config import Settings, get_settings
from regintel.container import Container, build_container
from regintel.observability import metrics
from regintel.observability.tracing import current_trace_id, setup_tracing, span

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_tracing(settings)
        if getattr(app.state, "container", None) is None:
            app.state.container = build_container(settings)
        yield

    app = FastAPI(
        title="RegIntel API",
        version=__version__,
        description="Agentic compliance intelligence: cited regulation Q&A, multi-agent "
        "document checks with human review, checklists and test generation.",
        lifespan=lifespan,
    )
    app.state.container = container

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if incoming.isalnum() and len(incoming) <= 64 else uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        route = request.url.path
        with span("http.request", route=route, request_id=request_id):
            response = await call_next(request)
            trace_id = current_trace_id()
        elapsed = time.perf_counter() - start
        metrics.REQUEST_LATENCY.labels(
            route if not route.startswith("/v1/checks/") else "/v1/checks/{id}",
            str(response.status_code),
        ).observe(elapsed)
        response.headers["x-request-id"] = request_id
        if trace_id:
            response.headers["x-trace-id"] = trace_id
        return response

    app.include_router(admin.router)
    app.include_router(ask.router)
    app.include_router(check.router)
    return app


app = create_app()
