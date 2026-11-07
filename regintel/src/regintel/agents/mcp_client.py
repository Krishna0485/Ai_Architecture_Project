"""Consume external MCP tools from inside agents (e.g. the ticketing server in the
regintel-mcp-servers repo). Used by finalize_report to file tickets for high-severity gaps.

The client runs the MCP session on a private event loop so it can be called from sync nodes.
We never forward the end user's credentials to the downstream server (no token passthrough):
the downstream server authenticates RegIntel itself with its own service token.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any


class MCPTicketingClient:  # pragma: no cover - exercised against the supporting repo
    def __init__(self, command: str, env: dict[str, str] | None = None) -> None:
        """``env`` is passed to the subprocess explicitly (the SDK only forwards a minimal safe
        environment), e.g. {"TICKETING_SERVICE_TOKEN": ..., "MCP_TOKENS": ...}."""
        parts = shlex.split(command, posix=True)
        self.command, self.args = parts[0], parts[1:]
        self.env = env or None

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self.command, args=self.args, env=self.env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            text = "".join(getattr(c, "text", "") for c in result.content)
            return json.loads(text) if text.startswith("{") else text

    def create_ticket(self, *, title: str, body: str, tenant_id: str) -> str:
        out = asyncio.run(
            self._call(
                "create_ticket",
                {
                    "title": title[:200],
                    "body": body[:2000],
                    "tenant_id": tenant_id,
                    "priority": "high",
                },
            )
        )
        return str(out.get("ticket_id") if isinstance(out, dict) else out)
