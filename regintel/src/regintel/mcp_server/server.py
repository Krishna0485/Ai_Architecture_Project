"""RegIntel as an MCP server (FastMCP).

Transports:
  * stdio - local clients (Claude Desktop / Claude Code). Identity = REGINTEL_MCP_DEFAULT_API_KEY.
  * streamable HTTP - bearer token = a RegIntel API key, verified by ``ApiKeyTokenVerifier``.

Security properties (docs/security.md#mcp):
  * Tools are narrow, typed and validated; descriptions are static and reviewed (no dynamic text
    that could carry tool-poisoning instructions).
  * Every call is authorised against the caller's SecurityContext and audited.
  * Client tokens are never forwarded to any downstream service (no token passthrough).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from regintel.agents.service import AgentsDisabledError, CheckNotFoundError
from regintel.agents.tools import ToolError
from regintel.api.auth import resolve_api_key
from regintel.config import ApiKeyGrant
from regintel.container import Container
from regintel.guardrails import PolicyDeniedError
from regintel.retrieval.base import SecurityContext

INSTRUCTIONS = (
    "RegIntel answers questions about indexed regulations (US GLBA Safeguards Rule, FMLA, "
    "Regulation B) with citations, runs compliance checks on uploaded documents, and generates "
    "compliance checklists. Results are informational, not legal advice."
)


class ApiKeyTokenVerifier:
    """Maps a bearer token (a RegIntel API key) to an AccessToken carrying tenant claims."""

    def __init__(self, grants: dict[str, ApiKeyGrant]) -> None:
        self.grants = grants

    async def verify_token(self, token: str) -> AccessToken | None:
        ctx = resolve_api_key(token, self.grants)
        if ctx is None:
            return None
        return AccessToken(
            token=hashlib.sha256(token.encode("utf-8")).hexdigest()[:16],  # never keep the raw key
            client_id=ctx.actor,
            scopes=["regintel"],
            claims={"tenant_id": ctx.tenant_id, "groups": list(ctx.groups)},
        )


def _ctx_from_token(token: AccessToken) -> SecurityContext:
    claims = token.claims or {}
    return SecurityContext(
        str(claims["tenant_id"]), tuple(claims.get("groups", [])), f"mcp:{token.client_id}"
    )


def build_server(
    container: Container,
    default_ctx: SecurityContext | None = None,
    *,
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    auth_kwargs: dict[str, Any] = {}
    if http:
        base = f"http://{host}:{port}"
        auth_kwargs = {
            "token_verifier": ApiKeyTokenVerifier(container.settings.api_keys),
            "auth": AuthSettings(
                issuer_url=AnyHttpUrl(base),
                resource_server_url=AnyHttpUrl(base),
                required_scopes=["regintel"],
            ),
        }
    mcp = FastMCP(
        "regintel",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        stateless_http=True,
        **auth_kwargs,
    )
    tools = container.tools

    def caller() -> SecurityContext:
        token = get_access_token()
        if token is not None:
            return _ctx_from_token(token)
        if default_ctx is not None:
            return default_ctx
        raise PermissionError("unauthenticated MCP caller")

    async def run(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return await anyio.to_thread.run_sync(fn)
        except PolicyDeniedError as exc:
            raise ToolError(f"permission denied: {exc}") from exc
        except CheckNotFoundError as exc:
            raise ToolError("not found") from exc
        except AgentsDisabledError as exc:
            raise ToolError("agent workflows are disabled") from exc

    @mcp.tool()
    async def search_regulations(
        query: str, jurisdiction: str | None = None, k: int = 5
    ) -> dict[str, Any]:
        """Search indexed regulations (hybrid BM25 + vector search with reranking).

        Args:
            query: natural-language query or section number, 3-500 characters.
            jurisdiction: optional filter, e.g. "US-FED".
            k: number of passages to return (1-10).
        Returns passages with chunk_id, citation, section, title, url, score and text.
        """
        ctx = caller()
        return await run(
            lambda: tools.search_regulations(ctx, query=query, jurisdiction=jurisdiction, k=k)
        )

    @mcp.tool()
    async def ask_regulations(question: str) -> dict[str, Any]:
        """Answer a question about the indexed regulations with citations (or abstain)."""
        ctx = caller()
        return await run(lambda: tools.ask(ctx, question))

    @mcp.tool()
    async def check_document(document_id: str) -> dict[str, Any]:
        """Start a compliance check of a previously uploaded document (id like doc_<12 hex>).
        Returns a check_id; findings require human review in the RegIntel UI/API."""
        ctx = caller()
        return await run(lambda: tools.check_document(ctx, document_id=document_id))

    @mcp.tool()
    async def get_check(check_id: str) -> dict[str, Any]:
        """Get the status and findings of a compliance check started by check_document."""
        ctx = caller()
        return await run(lambda: tools.get_check(ctx, check_id))

    @mcp.tool()
    async def get_checklist(section_id: str, source: str | None = None) -> dict[str, Any]:
        """Generate a compliance checklist and test scenarios for a regulation section,
        e.g. section_id "314.4" (source "16cfr314")."""
        ctx = caller()
        return await run(lambda: tools.get_checklist(ctx, section_id=section_id, source=source))

    return mcp
