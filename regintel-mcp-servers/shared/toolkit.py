"""Common server scaffolding: auth wiring + a guarded tool runner (validate -> authorise ->
execute -> audit). Tool errors are raised as ``ToolError`` so clients see ``isError=True``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl, BaseModel, ValidationError

from shared.audit import AuditLog
from shared.auth import AuthError, Principal, ScopedTokenVerifier, current_principal, require

T = TypeVar("T", bound=BaseModel)


class ToolError(RuntimeError):
    pass


def make_server(
    name: str, instructions: str, tokens: dict[str, Principal], *, http: bool, host: str, port: int
) -> FastMCP:
    kwargs: dict[str, Any] = {}
    if http:
        base = AnyHttpUrl(f"http://{host}:{port}")
        kwargs = {
            "token_verifier": ScopedTokenVerifier(tokens),
            "auth": AuthSettings(issuer_url=base, resource_server_url=base),
        }
    return FastMCP(
        name, instructions=instructions, host=host, port=port, stateless_http=True, **kwargs
    )


class Guard:
    def __init__(self, server: str, audit: AuditLog, default: Principal | None) -> None:
        self.server = server
        self.audit = audit
        self.default = default

    def run(
        self,
        tool: str,
        scope: str,
        model: type[T],
        raw: dict[str, Any],
        fn: Callable[[Principal, T], dict[str, Any]],
    ) -> dict[str, Any]:
        principal: Principal | None = None
        try:
            principal = current_principal(self.default)
            args = model.model_validate(raw)
            require(principal, scope)
        except ValidationError as exc:
            self.audit.record(self.server, principal, tool, raw, "invalid")
            raise ToolError(f"invalid arguments: {exc.errors(include_url=False)}") from exc
        except AuthError as exc:
            self.audit.record(self.server, principal, tool, raw, "deny", str(exc))
            raise ToolError(f"permission denied: {exc}") from exc
        try:
            result = fn(principal, args)
        except (KeyError, ValueError, PermissionError) as exc:
            self.audit.record(self.server, principal, tool, raw, "error", str(exc))
            raise ToolError(str(exc)) from exc
        self.audit.record(self.server, principal, tool, raw, "allow")
        return result
