"""Shared ``__main__`` logic: ``python -m servers.<name> [--transport stdio|http] [--port N]``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP

from shared.auth import Principal, load_tokens, stdio_principal


def run(
    build: Callable[..., FastMCP],
    default_port: int,
    token_vars: Sequence[str] = ("MCP_SERVICE_TOKEN",),
    argv: list[str] | None = None,
) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=default_port)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)  # stdout is the MCP channel
    tokens = load_tokens()
    kwargs: dict[str, Any] = {"tokens": tokens}
    if args.transport == "stdio":
        principal: Principal | None = stdio_principal(tokens, token_vars)
        if principal is None:
            print(f"set MCP_TOKENS and one of {list(token_vars)}", file=sys.stderr)
            return 2
        build(default_principal=principal, **kwargs).run("stdio")
    else:
        build(http=True, host=args.host, port=args.port, **kwargs).run("streamable-http")
    return 0
