from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from shared.auth import Principal


def principal(name: str, tenant: str, *scopes: str) -> Principal:
    return Principal(name, tenant, frozenset(scopes))


@asynccontextmanager
async def connect(server: FastMCP) -> AsyncIterator[ClientSession]:
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        yield client


async def call(client: ClientSession, tool: str, **args: Any) -> dict[str, Any]:
    res = await client.call_tool(tool, args)
    assert not res.isError, res.content
    return json.loads(res.content[0].text)  # type: ignore[union-attr,no-any-return]


async def call_error(client: ClientSession, tool: str, **args: Any) -> str:
    res = await client.call_tool(tool, args)
    assert res.isError, res.content
    return str(res.content[0].text)  # type: ignore[union-attr]


Builder = Callable[..., FastMCP]
