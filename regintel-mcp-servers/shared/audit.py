"""Append-only audit log for every tool call (allowed, denied or failed)."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.auth import Principal

_SECRETISH = re.compile(r"(token|secret|password|api[_-]?key)", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _scrub(value: Any, key: str = "") -> Any:
    if _SECRETISH.search(key):
        return "<redacted>"
    if isinstance(value, str):
        return _EMAIL.sub("<EMAIL>", value[:500])
    if isinstance(value, dict):
        return {k: _scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value[:50]]
    return value


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        server: str,
        principal: Principal | None,
        tool: str,
        args: dict[str, Any],
        decision: str,
        detail: str = "",
    ) -> None:
        event = {
            "ts": datetime.now(UTC).isoformat(),
            "server": server,
            "tool": tool,
            "principal": principal.name if principal else None,
            "tenant_id": principal.tenant_id if principal else None,
            "args": _scrub(args),
            "decision": decision,
            "detail": detail[:300],
        }
        with self._lock:
            self.events.append(event)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event) + "\n")
