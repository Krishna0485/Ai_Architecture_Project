"""Call the RegIntel MCP server through a real MCP client session (in-memory transport)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from regintel.config import ApiKeyGrant
from regintel.container import Container
from regintel.mcp_server.server import ApiKeyTokenVerifier, build_server
from regintel.retrieval.base import SecurityContext
from tests.conftest import synthetic

pytestmark = pytest.mark.integration
CTX = SecurityContext("acme", ("compliance",), "mcp-test")


def _json(result: Any) -> dict[str, Any]:
    assert not result.isError, result.content
    return json.loads(result.content[0].text)  # type: ignore[no-any-return]


async def test_tools_are_listed_with_schemas(container: Container) -> None:
    server = build_server(container, CTX)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {
            "search_regulations",
            "ask_regulations",
            "check_document",
            "get_check",
            "get_checklist",
        } <= set(tools)
        assert "query" in tools["search_regulations"].inputSchema["properties"]


async def test_search_ask_check_and_checklist_via_mcp(container: Container) -> None:
    server = build_server(container, CTX)
    doc = container.documents.add("acme", "p.md", synthetic("acme_infosec_policy_gaps.md"))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        res = _json(
            await client.call_tool(
                "search_regulations", {"query": "multi-factor authentication", "k": 3}
            )
        )
        assert len(res["results"]) == 3 and res["results"][0]["chunk_id"].startswith("16cfr314")
        ans = _json(
            await client.call_tool(
                "ask_regulations", {"question": "How many workweeks of FMLA leave?"}
            )
        )
        assert ans["citations"]
        started = _json(await client.call_tool("check_document", {"document_id": doc.id}))
        view = _json(await client.call_tool("get_check", {"check_id": started["check_id"]}))
        assert view["status"] == "awaiting_review"
        cl = _json(await client.call_tool("get_checklist", {"section_id": "314.4"}))
        assert cl["checklist"]
        bad = await client.call_tool("search_regulations", {"query": "x"})
        assert bad.isError
        missing = await client.call_tool("get_check", {"check_id": "chk_000000000000"})
        assert missing.isError


async def test_policy_denial_is_a_tool_error(container: Container) -> None:
    reader = SecurityContext("acme", ("reader",), "r")
    server = build_server(container, reader)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        res = await client.call_tool("check_document", {"document_id": "doc_0123456789ab"})
        assert res.isError and "permission denied" in res.content[0].text  # type: ignore[union-attr]


async def test_unauthenticated_caller_rejected(container: Container) -> None:
    server = build_server(container, None)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        res = await client.call_tool("search_regulations", {"query": "encryption"})
        assert res.isError


async def test_token_verifier_maps_keys_to_tenant_claims() -> None:
    v = ApiKeyTokenVerifier({"secret-key": ApiKeyGrant(tenant_id="acme", groups=["compliance"])})
    tok = await v.verify_token("secret-key")
    assert tok is not None and tok.claims == {"tenant_id": "acme", "groups": ["compliance"]}
    assert "secret-key" not in tok.token  # raw key is never kept
    assert await v.verify_token("nope") is None


def test_http_server_builds_with_auth(container: Container) -> None:
    server = build_server(container, http=True, port=8123)
    app = server.streamable_http_app()
    assert app is not None
