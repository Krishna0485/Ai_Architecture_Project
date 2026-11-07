"""``python -m servers.checklist``"""

from servers.checklist.server import build_server
from servers.cli import run

if __name__ == "__main__":
    raise SystemExit(run(build_server, default_port=8102))
