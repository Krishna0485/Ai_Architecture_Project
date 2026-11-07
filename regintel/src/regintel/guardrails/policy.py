"""OPA-style policy decisions for tools and actions. Deny by default."""

from __future__ import annotations

from dataclasses import dataclass

from regintel.retrieval.base import SecurityContext


class PolicyDeniedError(PermissionError):
    pass


@dataclass(frozen=True)
class Rule:
    action: str
    any_of_groups: frozenset[str]
    same_tenant_only: bool = True


DEFAULT_RULES: dict[str, Rule] = {
    r.action: r
    for r in [
        Rule("ask", frozenset({"compliance", "hr", "admin", "reader"})),
        Rule("search_regulations", frozenset({"compliance", "hr", "admin", "reader"})),
        Rule("upload_document", frozenset({"compliance", "hr", "admin"})),
        Rule("check_document", frozenset({"compliance", "hr", "admin"})),
        Rule("review_check", frozenset({"compliance", "admin"})),
        Rule("get_checklist", frozenset({"compliance", "hr", "admin"})),
        Rule("read_audit", frozenset({"admin"})),
        Rule("create_ticket", frozenset({"compliance", "admin"})),
    ]
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class PolicyEngine:
    def __init__(self, rules: dict[str, Rule] | None = None) -> None:
        self.rules = rules or DEFAULT_RULES

    def decide(
        self, ctx: SecurityContext, action: str, resource_tenant: str | None = None
    ) -> Decision:
        rule = self.rules.get(action)
        if rule is None:
            return Decision(False, f"no rule for action {action!r} (deny by default)")
        if not set(ctx.groups) & rule.any_of_groups:
            return Decision(False, f"groups {list(ctx.groups)} lack {sorted(rule.any_of_groups)}")
        if rule.same_tenant_only and resource_tenant not in (None, ctx.tenant_id):
            return Decision(False, "cross-tenant access denied")
        return Decision(True, "allowed")

    def authorize(
        self, ctx: SecurityContext, action: str, resource_tenant: str | None = None
    ) -> None:
        decision = self.decide(ctx, action, resource_tenant)
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason)
