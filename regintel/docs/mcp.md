# MCP server

RegIntel exposes its capabilities as an MCP server built with FastMCP (`mcp` 1.x, ADR-0006).

## Tools

| Tool | Arguments | Returns | Policy action |
|---|---|---|---|
| `search_regulations` | `query` (3-500 chars), `jurisdiction?` (e.g. `US-FED`), `k` (1-10) | passages with chunk id, citation, section, url, score, text | `search_regulations` |
| `ask_regulations` | `question` | cited answer or abstention | `ask` |
| `check_document` | `document_id` (`doc_<12 hex>`) | `check_id`, status | `check_document` |
| `get_check` | `check_id` | status, findings, report | `check_document` |
| `get_checklist` | `section_id` (e.g. `314.4`), `source?` (e.g. `16cfr314`) | checklist items + pytest/BDD scenarios | `get_checklist` |

Every call validates arguments (Pydantic), authorises against the caller's `SecurityContext`,
and writes an audit event (`tool:<name>`, allow or deny). Policy denials and invalid arguments
come back as MCP tool errors.

## Claude Desktop / Claude Code (stdio)

```json
{
  "mcpServers": {
    "regintel": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/regintel", "python", "-m", "regintel.mcp_server"],
      "env": { "REGINTEL_MCP_DEFAULT_API_KEY": "<a key from REGINTEL_API_KEYS>" }
    }
  }
}
```

Claude Code: `claude mcp add regintel -- uv run --directory /path/to/regintel python -m regintel.mcp_server`
(set `REGINTEL_MCP_DEFAULT_API_KEY` in the environment). Then ask, for example: *"Use regintel to
find what 16 CFR 314.4 says about multi-factor authentication."*

## Streamable HTTP

```bash
python -m regintel.mcp_server --transport http --host 127.0.0.1 --port 8000   # or the `mcp` compose service
```

Clients connect to `http://<host>:8000/mcp` with `Authorization: Bearer <RegIntel API key>`. The
token verifier maps the key to tenant claims and keeps only a hash of the token. The server is
stateless-HTTP so it scales horizontally behind a load balancer.

## Consuming MCP tools from agents

`agents/mcp_client.py` lets `finalize_report` file tickets for high-severity gaps through the
ticketing server in the `regintel-mcp-servers` repository (set `REGINTEL_TICKETING_MCP_COMMAND`).
RegIntel authenticates to that server with its own service token; end-user tokens are never
forwarded.

## Tests

`tests/integration/test_mcp.py` drives the server through a real MCP client session (in-memory
transport): tool listing and schemas, search/ask/check/checklist round trips, validation errors,
policy denials, unauthenticated callers, token verification and HTTP app construction.
