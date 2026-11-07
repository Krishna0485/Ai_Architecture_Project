from __future__ import annotations

import json
from pathlib import Path

import pytest

from servers.checklist import build_server as build_checklist
from servers.cli import run
from shared.audit import AuditLog
from shared.auth import (
    AuthError,
    ScopedTokenVerifier,
    current_principal,
    load_tokens,
    parse_tokens,
    require,
    resolve,
    stdio_principal,
)
from tests.conftest import call_error, connect, principal

TOKENS_JSON = json.dumps({"tok-a": {"name": "svc", "tenant_id": "acme", "scopes": ["x:read"]}})


def test_token_parsing_and_resolution() -> None:
    tokens = parse_tokens(TOKENS_JSON)
    assert resolve("tok-a", tokens) == principal("svc", "acme", "x:read")
    assert resolve("nope", tokens) is None and resolve(None, tokens) is None
    assert parse_tokens(None) == {} and load_tokens({}) == {}
    assert load_tokens({"MCP_TOKENS": TOKENS_JSON})["tok-a"].name == "svc"
    env = {"TICKETING_SERVICE_TOKEN": "tok-a"}
    assert (
        stdio_principal(tokens, ("MCP_SERVICE_TOKEN", "TICKETING_SERVICE_TOKEN"), env) is not None
    )
    assert stdio_principal(tokens, ("MCP_SERVICE_TOKEN",), env) is None


async def test_verifier_keeps_only_a_hash() -> None:
    v = ScopedTokenVerifier(parse_tokens(TOKENS_JSON))
    tok = await v.verify_token("tok-a")
    assert tok is not None and tok.token != "tok-a" and tok.claims == {"tenant_id": "acme"}
    assert tok.scopes == ["x:read"] and await v.verify_token("bad") is None


def test_require_and_unauthenticated() -> None:
    with pytest.raises(AuthError):
        require(principal("a", "t"), "x:write")
    with pytest.raises(AuthError):
        current_principal(None)


async def test_unauthenticated_tool_call_is_error() -> None:
    async with connect(build_checklist(default_principal=None)) as c:
        assert "permission denied" in await call_error(c, "list_checklists")


def test_audit_scrubs_secrets_and_emails(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a" / "audit.jsonl")
    log.record(
        "s",
        principal("a", "t"),
        "tool",
        {"api_key": "sk-123", "note": "mail a@b.co", "items": ["x"] * 60},
        "allow",
    )
    raw = (tmp_path / "a" / "audit.jsonl").read_text(encoding="utf-8")
    assert "sk-123" not in raw and "a@b.co" not in raw
    assert len(json.loads(raw)["args"]["items"]) == 50


def test_cli_requires_identity_for_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_TOKENS", raising=False)
    assert run(build_checklist, 8102, argv=["--transport", "stdio"]) == 2


def test_http_server_builds() -> None:
    server = build_checklist(tokens=parse_tokens(TOKENS_JSON), http=True, port=8999)
    assert server.streamable_http_app() is not None
