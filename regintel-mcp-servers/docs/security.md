# Security design

## Threats and mitigations

| Threat | Mitigation | Test |
|---|---|---|
| **Tool poisoning** (malicious instructions in tool names/descriptions or server instructions) | All descriptions are static, reviewed strings in code; nothing data-derived is placed in tool metadata; tool results are data, and `fetch_document` documents its content as untrusted | review + `test_missing_scope_and_no_write_tools` pins the docstore tool surface |
| **Token passthrough** (server forwards the client's token to other APIs) | Tokens are verified locally by `ScopedTokenVerifier`; only a SHA-256 prefix is kept on the `AccessToken`; servers never call downstream services with caller tokens | `test_verifier_keeps_only_a_hash` |
| **Confused deputy / cross-tenant access** | Tenant comes from the principal; ids from other tenants raise the same "not found" as missing ids; on-behalf-of requires the explicit `tickets:cross_tenant` scope | `test_search_respects_tenant_and_groups`, `test_cross_tenant_requires_scope_and_isolation` |
| **Excessive agency** | Narrow tools (no bulk delete, no generic update, no query language); docstore is read-only; high-priority tickets require human approval by someone other than the creator; legal state transitions only | `test_high_priority_requires_approval_by_someone_else`, `test_reject_requires_approver` |
| **Injection through arguments** | Every argument is validated with Pydantic (lengths, patterns, enums) before any logic runs | `invalid arguments` assertions in every test module |
| **Repudiation** | Audit log of every call with principal, tenant, scrubbed args and decision (`allow`/`deny`/`invalid`/`error`) | `test_audit_scrubs_secrets_and_emails` |
| **Secrets / PII in logs** | Audit scrubs secret-like keys and email addresses, truncates values; logs go to stderr (stdout is the MCP channel) | same |
| **Unauthenticated access** | stdio refuses to start without a resolvable identity; HTTP requires a bearer token; tool calls without a principal fail | `test_cli_requires_identity_for_stdio`, `test_unauthenticated_tool_call_is_error` |
| **Supply chain / protocol drift** | `mcp>=1.9,<2` pinned; small surface to migrate to the 2.x `MCPServer` API | - |

## Principals and scopes

`MCP_TOKENS` maps opaque random tokens to `{name, tenant_id, scopes}`. Generate tokens with
`python -c "import secrets; print(secrets.token_urlsafe(32))"` and store them in a secret
manager; never commit them. Rotate by adding the new token, deploying, then removing the old one.

## Known limitations

- In-memory stores (by design for a reference implementation); production would back them with
  a database using the same tenant-scoped queries.
- Static token map; for multi-organisation use, swap `ScopedTokenVerifier` for OAuth 2.1 token
  introspection (the MCP SDK's `TokenVerifier` protocol stays the same).
