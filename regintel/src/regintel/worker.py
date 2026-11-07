"""Queue worker for long document checks (``REGINTEL_CHECK_EXECUTOR=queue``).

The API enqueues {check_id, input} on a Redis list; workers run the graph. Because the LangGraph
checkpointer is Postgres in this mode, any worker (or the API) can resume a check after review.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.types import Command

from regintel.config import get_settings
from regintel.container import build_container

log = logging.getLogger(__name__)
QUEUE_KEY = "regintel:checks"


class RedisCheckQueue:
    def __init__(self, url: str) -> None:
        import redis

        self._r: Any = redis.Redis.from_url(url, decode_responses=True)

    def enqueue(self, check_id: str, graph_input: Any) -> None:
        payload = (
            {"resume": graph_input.resume}
            if isinstance(graph_input, Command)
            else {"input": graph_input}
        )
        self._r.rpush(QUEUE_KEY, json.dumps({"check_id": check_id, **payload}))

    def pop(self, timeout: int = 5) -> dict[str, Any] | None:
        item = self._r.blpop([QUEUE_KEY], timeout=timeout)
        return json.loads(item[1]) if item else None


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    container = build_container(settings)
    queue = RedisCheckQueue(settings.redis_url)
    log.info("worker started; waiting for checks on %s", QUEUE_KEY)
    while True:
        job = queue.pop()
        if job is None:
            continue
        graph_input: Any = Command(resume=job["resume"]) if "resume" in job else job["input"]
        container.checks._run(job["check_id"], graph_input)


if __name__ == "__main__":
    raise SystemExit(main())
