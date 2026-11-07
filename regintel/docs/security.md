# Security

## Assets and trust boundaries

| Asset | Why it matters |
|---|---|
| Tenant documents and tenant-private guidance | confidentiality across customers |
| Findings and review decisions | integrity of compliance outcomes |
| API keys, gateway keys, DSNs | full account / data access |
| PII in uploads (employees, customers) | privacy, regulatory exposure |
| Model spend | availability and cost |

Trust boundaries: client -> API/MCP (authentication), API -> model (untrusted output), upload ->
quarantined extractor (untrusted input), RegIntel -> downstream MCP servers (no token passthrough).

## Threat model (STRIDE)

| Threat | Example | Controls | Tests |
|---|---|---|---|
| **S**poofing | forged tenant in request body; stolen key | tenant/groups only from the API-key grant (`resolve_api_key`, constant-time compare); MCP bearer tokens verified; reviewer identity from auth, not body | `test_tenant_comes_from_key_not_from_body`, `test_service_lifecycle...` (spoofed reviewer) |
| **T**ampering | injected text flips findings to compliant | quarantine pattern (ADR-0005), schema validation, catalogue-defined requirements, `needs_review` on malformed output, human review | `test_indirect_injection_cannot_change_findings`, `test_injected_text_never_reaches_privileged_prompts` |
| **R**epudiation | "I never approved that" | audit events for ask/upload/check/review/tool calls (allow and deny), request ids, OTel trace ids | `test_tools_validate_authorise_and_audit`, audit tests |
| **I**nformation disclosure | cross-tenant retrieval; PII in logs; prompt leakage | security filters inside the stores (memory, Qdrant payload filter, OpenSearch filter); tenant-scoped documents/checks/audit (404 not 403); PII redaction before storage, before models and in audit details; output PII scan | `tests/security/test_tenant_isolation.py`, `test_uploaded_pii_is_redacted_everywhere` |
| **D**enial of service | huge uploads, token floods | request validation limits (200k chars, question 1000), per-request and per-tenant daily token budgets, timeouts, step limits, HPA | `test_budgets`, `test_input_validation` |
| **E**levation of privilege | reader starts checks; model triggers a tool | deny-by-default `PolicyEngine` per action; check graph has no tool-calling path; MCP tools narrow and validated | `test_policy_engine`, `test_agents_have_no_tool_calling_path`, `test_policy_denial_is_a_tool_error` |

## OWASP Top 10 for LLM Applications (2025) mapping

| Risk | Status | How |
|---|---|---|
| LLM01 Prompt injection | mitigated | `<untrusted>` wrapping + spoof-tag neutralisation, injection scanner on uploads and retrieved chunks (quarantine), dual-LLM quarantine for checks, red-team suite |
| LLM02 Sensitive information disclosure | mitigated | PII redaction (regex + Presidio), tenant isolation in stores, audit redaction, output PII scan |
| LLM03 Supply chain | mitigated | locked deps (uv.lock), Dependabot, CodeQL, Trivy, pinned images, MCP SDK pinned (ADR-0006) |
| LLM04 Data and model poisoning | partial | public corpus from official source with manifest/licence; poisoned retrieved chunks quarantined; no fine-tuning on user data |
| LLM05 Improper output handling | mitigated | citations validated against supplied ids, HTML escaped, links allow-listed, model output never executed (SQL only via bound parameters), generated tests AST-validated and never run |
| LLM06 Excessive agency | mitigated | fixed graph, no autonomous tool use, human approval before final report, kill switch |
| LLM07 System prompt leakage | mitigated | no secrets in prompts; probes in red-team suite |
| LLM08 Vector and embedding weaknesses | mitigated | per-tenant payload filters, group ACLs, tenant-namespaced semantic cache |
| LLM09 Misinformation | partial | grounded answers with citations, abstention, "not legal advice"; residual risk documented |
| LLM10 Unbounded consumption | mitigated | token budgets, timeouts, step limits, LiteLLM `max_budget`, caching |

## MCP-specific risks

- **Tool poisoning:** tool names/descriptions are static strings reviewed in code; no
  descriptions are generated from data. Server instructions contain no dynamic text.
- **Token passthrough:** RegIntel never forwards a client's token downstream. The MCP server
  verifies the bearer token and keeps only a hash; the ticketing MCP client authenticates with
  RegIntel's own service token.
- **Least privilege:** tools are narrow (search, ask, start check, get check, checklist). There
  is no generic "run query" or "read file" tool. Writes (starting a check) still require human
  review before anything becomes final.
- **Version pinning:** `mcp>=1.9,<2` with a documented migration (ADR-0006).
- **Transport:** stdio for local clients (identity from config); streamable HTTP requires a
  bearer token and binds to localhost by default (DNS-rebinding protection enabled by the SDK).

## Guardrail inventory

| Guard | Where | Module |
|---|---|---|
| PII redaction | question, upload, audit details, model output | `guardrails/pii.py` |
| Injection scan | uploads (flag + line quarantine), retrieved chunks (drop), extracted facts (drop) | `guardrails/injection.py` |
| Untrusted wrapping | every passage/document in prompts | `guardrails/untrusted.py` |
| Output validation | schema parsing, citation validation, link allow-list, HTML escaping | `guardrails/output_validation.py` |
| Policy | every API action and tool call | `guardrails/policy.py` |

## Known limitations

- Regex PII misses names/addresses unless Presidio is enabled (`REGINTEL_PII_BACKEND=presidio`).
- The heuristic injection scanner is bypassable (paraphrase, other languages); it is defence in
  depth, not the primary control.
- BM25 IDF statistics are computed over the whole index (all tenants). Results are filtered, but
  term statistics can leak a weak signal about other tenants' vocabulary; per-tenant indexes
  remove this at higher cost.
- An attacker can still put false *facts* in their own document (e.g. claim MFA exists);
  verifying facts against evidence is a human-review responsibility.
- Dev API keys in `config.py` are for local use only; production must set `REGINTEL_API_KEYS`.

## Running the security tests

```bash
uv run pytest tests/security -q
npx promptfoo@latest eval -c evals/redteam/promptfooconfig.yaml   # against a running API + real model
```
