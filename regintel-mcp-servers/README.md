# regintel-mcp-servers

> Three small, reusable MCP servers built secure-by-default: a tenant-scoped **document store**,
> a **compliance checklist** service with narrow write tools, and a **ticketing mock** that
> demonstrates approvals and separation of duties.

[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![mcp](https://img.shields.io/badge/MCP-FastMCP%201.x-purple)](https://modelcontextprotocol.io)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

These servers are used by [RegIntel](https://github.com/Krishna0485/Ai_Architecture_Project/tree/main/regintel). For example, its
compliance-check agent files remediation tickets through `ticketing_mock`. They work with any
MCP client (Claude Desktop, Claude Code, custom agents).

| Server | Tools | Scopes |
|---|---|---|
| `servers.docstore` | `search_documents`, `fetch_document` (read-only by design) | `docs:read`, `group:<name>` ACLs |
| `servers.checklist` | `create_checklist`, `add_item`, `set_item_status`, `get_checklist`, `list_checklists`, `archive_checklist` | `checklist:read`, `checklist:write`, `checklist:admin` |
| `servers.ticketing_mock` | `create_ticket`, `approve_ticket`, `update_ticket`, `get_ticket`, `list_tickets` | `tickets:read`, `tickets:write`, `tickets:approve`, `tickets:cross_tenant` |

## Security model (short)

Details: [docs/security.md](docs/security.md).

- Every tool goes through one guard: **validate args (Pydantic) -> authenticate -> check scope
  -> execute -> audit**. Denials and validation failures are audited too.
- Tenant comes from the authenticated principal, never from tool arguments (the single,
  explicit exception is `tickets:cross_tenant` for on-behalf-of filing).
- "Not found" and "forbidden" look identical, so callers can't probe other tenants' ids.
- High-priority tickets need approval by a *different* principal; an agent can propose work
  but cannot approve it.
- Tokens are verified and only a hash is kept; nothing is forwarded downstream.

## Run

```bash
uv sync
export MCP_TOKENS='{"<random-token>": {"name": "regintel-svc", "tenant_id": "acme",
                     "scopes": ["tickets:write", "tickets:read"]}}'
# stdio (identity from MCP_SERVICE_TOKEN / TICKETING_SERVICE_TOKEN)
MCP_SERVICE_TOKEN=<random-token> uv run python -m servers.ticketing_mock
# streamable HTTP (clients send Authorization: Bearer <token>)
uv run python -m servers.ticketing_mock --transport http --port 8103
```

Claude Desktop config:

```json
{ "mcpServers": { "tickets": {
    "command": "uv", "args": ["run", "--directory", "/path/to/regintel-mcp-servers",
                              "python", "-m", "servers.ticketing_mock"],
    "env": { "MCP_TOKENS": "{...}", "MCP_SERVICE_TOKEN": "<token>" } } } }
```

## Develop

```bash
uv sync --group dev
uv run pytest            # tools exercised through real MCP client sessions
uv run ruff check . && uv run mypy
```

MIT licensed.
