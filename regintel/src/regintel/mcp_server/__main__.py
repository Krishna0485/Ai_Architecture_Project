"""``python -m regintel.mcp_server [--transport stdio|http] [--port 8000]``"""

from __future__ import annotations

import argparse
import logging
import sys

from regintel.api.auth import resolve_api_key
from regintel.config import get_settings
from regintel.container import build_container
from regintel.mcp_server.server import build_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RegIntel MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    # stdio: stdout is the protocol channel - logs must go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    settings = get_settings()
    container = build_container(settings)
    if args.transport == "stdio":
        key = settings.mcp_default_api_key
        ctx = resolve_api_key(key.get_secret_value() if key else None, settings.api_keys)
        if ctx is None:
            print("set REGINTEL_MCP_DEFAULT_API_KEY to a valid API key", file=sys.stderr)
            return 2
        build_server(container, ctx).run("stdio")
    else:
        build_server(container, http=True, host=args.host, port=args.port).run("streamable-http")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
