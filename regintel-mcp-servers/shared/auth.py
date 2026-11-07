"""Authentication and authorisation shared by every server.

* Tokens map to a ``Principal`` (name, tenant, scopes) via ``MCP_TOKENS`` - a JSON object
  ``{"<token>": {"name": "...", "tenant_id": "...", "scopes": ["docs:read", ...]}}``.
* streamable HTTP: the bearer token is verified by ``ScopedTokenVerifier`` (only a hash of the
  token is kept); stdio: the identity comes from ``MCP_SERVICE_TOKEN`` (or a server-specific
  variable such as ``TICKETING_SERVICE_TOKEN``).
* Tokens are never forwarded anywhere (no token passthrough).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken


class AuthError(PermissionError):
    """Raised when a caller is unauthenticated or lacks a scope."""


@dataclass(frozen=True)
class Principal:
    name: str
    tenant_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has(self, scope: str) -> bool:
        return scope in self.scopes


def parse_tokens(raw: str | None) -> dict[str, Principal]:
    if not raw:
        return {}
    data = json.loads(raw)
    return {
        token: Principal(str(v["name"]), str(v["tenant_id"]), frozenset(v.get("scopes", [])))
        for token, v in data.items()
    }


def load_tokens(env: Mapping[str, str] | None = None) -> dict[str, Principal]:
    return parse_tokens((env if env is not None else os.environ).get("MCP_TOKENS"))


def resolve(token: str | None, tokens: Mapping[str, Principal]) -> Principal | None:
    if not token:
        return None
    for known, principal in tokens.items():
        if hmac.compare_digest(known.encode(), token.encode()):
            return principal
    return None


def stdio_principal(
    tokens: Mapping[str, Principal],
    token_vars: Sequence[str] = ("MCP_SERVICE_TOKEN",),
    env: Mapping[str, str] | None = None,
) -> Principal | None:
    source = env if env is not None else os.environ
    for var in token_vars:
        principal = resolve(source.get(var), tokens)
        if principal is not None:
            return principal
    return None


class ScopedTokenVerifier:
    """MCP ``TokenVerifier`` implementation for streamable HTTP."""

    def __init__(self, tokens: Mapping[str, Principal]) -> None:
        self.tokens = dict(tokens)

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = resolve(token, self.tokens)
        if principal is None:
            return None
        return AccessToken(
            token=hashlib.sha256(token.encode()).hexdigest()[:16],
            client_id=principal.name,
            scopes=sorted(principal.scopes),
            claims={"tenant_id": principal.tenant_id},
        )


def current_principal(default: Principal | None) -> Principal:
    """The authenticated caller: HTTP bearer token if present, else the stdio identity."""
    token = get_access_token()
    if token is not None:
        claims = token.claims or {}
        return Principal(token.client_id, str(claims["tenant_id"]), frozenset(token.scopes))
    if default is not None:
        return default
    raise AuthError("unauthenticated caller")


def require(principal: Principal, scope: str) -> None:
    if not principal.has(scope):
        raise AuthError(f"{principal.name} lacks scope {scope!r}")
