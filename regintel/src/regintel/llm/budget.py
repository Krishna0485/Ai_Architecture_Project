"""Token budgets: per-request ceiling and per-tenant daily allowance."""

from __future__ import annotations

import threading
import time

from regintel.llm.base import BudgetExceededError


class TokenBudget:
    def __init__(self, per_request: int, tenant_daily: int) -> None:
        self.per_request = per_request
        self.tenant_daily = tenant_daily
        self._used: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _day() -> int:
        return int(time.time() // 86_400)

    def check(self, tenant_id: str, prompt_tokens: int, max_output_tokens: int) -> None:
        requested = prompt_tokens + max_output_tokens
        if requested > self.per_request:
            raise BudgetExceededError(
                f"request needs ~{requested} tokens, per-request budget is {self.per_request}"
            )
        if self.used_today(tenant_id) + requested > self.tenant_daily:
            raise BudgetExceededError(f"tenant {tenant_id} exceeded its daily token budget")

    def record(self, tenant_id: str, tokens: int) -> None:
        key = (tenant_id, self._day())
        with self._lock:
            self._used[key] = self._used.get(key, 0) + tokens

    def used_today(self, tenant_id: str) -> int:
        return self._used.get((tenant_id, self._day()), 0)
