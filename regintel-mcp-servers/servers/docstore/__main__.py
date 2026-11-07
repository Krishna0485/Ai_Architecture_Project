"""``python -m servers.docstore`` - seed with DOCSTORE_PATH (JSON list of documents)."""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from servers.cli import run
from servers.docstore.server import DocStore, build_server

if __name__ == "__main__":
    path = os.environ.get("DOCSTORE_PATH")
    store = DocStore.from_json(Path(path)) if path else DocStore()
    raise SystemExit(run(partial(build_server, store), default_port=8101))
