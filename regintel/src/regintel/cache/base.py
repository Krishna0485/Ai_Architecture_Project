"""Cache contracts and backends (in-memory, Redis)."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Protocol


class KeyValueCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class ListBackend(Protocol):
    """Append-only list per namespace; used by the semantic cache for candidate scans."""

    def append(self, namespace: str, item: str) -> None: ...

    def items(self, namespace: str) -> list[str]: ...

    def clear(self) -> None: ...


class InMemoryCache:
    """Thread-safe LRU with TTL. Implements both KeyValueCache and ListBackend."""

    def __init__(self, max_items: int = 10_000, ttl_s: int = 86_400) -> None:
        self.max_items = max_items
        self.ttl_s = ttl_s
        self._kv: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lists: dict[str, list[tuple[float, str]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._kv.get(key)
            if row is None:
                return None
            ts, value = row
            if time.time() - ts > self.ttl_s:
                del self._kv[key]
                return None
            self._kv.move_to_end(key)
            return value

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._kv[key] = (time.time(), value)
            self._kv.move_to_end(key)
            while len(self._kv) > self.max_items:
                self._kv.popitem(last=False)

    def append(self, namespace: str, item: str) -> None:
        with self._lock:
            rows = self._lists.setdefault(namespace, [])
            rows.append((time.time(), item))
            if len(rows) > self.max_items:
                del rows[0]

    def items(self, namespace: str) -> list[str]:
        now = time.time()
        with self._lock:
            return [v for ts, v in self._lists.get(namespace, []) if now - ts <= self.ttl_s]

    def clear(self) -> None:
        with self._lock:
            self._kv.clear()
            self._lists.clear()


class RedisCache:  # pragma: no cover - needs redis service
    def __init__(self, url: str, ttl_s: int = 86_400, prefix: str = "regintel:") -> None:
        import redis

        self._r: Any = redis.Redis.from_url(url, decode_responses=True)
        self.ttl_s = ttl_s
        self.prefix = prefix

    def get(self, key: str) -> str | None:
        value = self._r.get(self.prefix + key)
        return str(value) if value is not None else None

    def set(self, key: str, value: str) -> None:
        self._r.set(self.prefix + key, value, ex=self.ttl_s)

    def append(self, namespace: str, item: str) -> None:
        k = f"{self.prefix}sem:{namespace}"
        self._r.rpush(k, item)
        self._r.ltrim(k, -5000, -1)
        self._r.expire(k, self.ttl_s)

    def items(self, namespace: str) -> list[str]:
        return [str(x) for x in self._r.lrange(f"{self.prefix}sem:{namespace}", 0, -1)]

    def clear(self) -> None:
        for k in self._r.scan_iter(self.prefix + "*"):
            self._r.delete(k)
