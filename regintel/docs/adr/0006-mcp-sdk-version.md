# ADR-0006: Pin the MCP Python SDK to 1.x (FastMCP)

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The official `mcp` package 2.x renamed `FastMCP` to `MCPServer` (`mcp.server.mcpserver`) and
changed other APIs. The 1.x line (1.30 at the time of writing) provides the stable FastMCP API,
`TokenVerifier`-based auth for streamable HTTP, and in-memory client sessions for tests.

## Decision
Pin `mcp>=1.9,<2`. All MCP code is isolated in `src/regintel/mcp_server/` and
`src/regintel/agents/mcp_client.py`, and covered by `tests/integration/test_mcp.py`.

## Migration path to 2.x
1. Replace `from mcp.server.fastmcp import FastMCP` with `from mcp.server.mcpserver import MCPServer`.
2. Re-check auth wiring (`token_verifier`, `AuthSettings`) and transport options in the 2.x docs.
3. Run `tests/integration/test_mcp.py`; update the in-memory session helper if renamed.

## Consequences
- Positive: stable, well-documented API now; small, tested surface to migrate later.
- Negative: we will miss 2.x features until migrated; Dependabot will propose 2.x - reject until
  the migration PR is done.
