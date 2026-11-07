"""``python -m servers.ticketing_mock`` - stdio identity from TICKETING_SERVICE_TOKEN."""

from servers.cli import run
from servers.ticketing_mock.server import build_server

if __name__ == "__main__":
    raise SystemExit(
        run(
            build_server,
            default_port=8103,
            token_vars=("TICKETING_SERVICE_TOKEN", "MCP_SERVICE_TOKEN"),
        )
    )
