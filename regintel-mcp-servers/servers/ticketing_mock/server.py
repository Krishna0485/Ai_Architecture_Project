"""ticketing_mock: create and update tickets, with an approval step for high-priority tickets.

Security properties demonstrated:
* **Approvals / separation of duties:** ``high`` tickets start ``pending_approval`` and can only be
  approved by a principal with ``tickets:approve`` who is not the creator. An agent (e.g. RegIntel)
  can *propose* work but cannot approve it.
* **On-behalf-of without token passthrough:** a service principal may file a ticket for another
  tenant only with the explicit ``tickets:cross_tenant`` scope; otherwise ``tenant_id`` is
  ignored and the caller's own tenant is used.
* **State machine:** only legal status transitions are accepted.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from shared.audit import AuditLog
from shared.auth import Principal
from shared.toolkit import Guard, make_server

NAME = "ticketing"
Priority = Literal["low", "medium", "high"]
TRANSITIONS: dict[str, set[str]] = {
    "pending_approval": {"rejected"},  # approval goes through approve_ticket only
    "open": {"in_progress", "closed"},
    "in_progress": {"open", "closed"},
    "closed": set(),
    "rejected": set(),
}


@dataclass
class Ticket:
    id: str
    tenant_id: str
    title: str
    body: str
    priority: str
    created_by: str
    status: str
    approved_by: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)

    def view(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class TicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def add(self, t: Ticket) -> Ticket:
        with self._lock:
            self._tickets[t.id] = t
        return t

    def get(self, p: Principal, ticket_id: str) -> Ticket:
        t = self._tickets.get(ticket_id)
        if t is None or (t.tenant_id != p.tenant_id and not p.has("tickets:cross_tenant")):
            raise KeyError(f"ticket {ticket_id} not found")
        return t

    def list(self, p: Principal, status: str | None) -> list[Ticket]:
        return [
            t
            for t in self._tickets.values()
            if t.tenant_id == p.tenant_id and (status is None or t.status == status)
        ]


def _event(actor: str, action: str, note: str = "") -> dict[str, str]:
    return {"ts": datetime.now(UTC).isoformat(), "actor": actor, "action": action, "note": note}


class CreateArgs(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(default="", max_length=4000)
    priority: Priority = "medium"
    tenant_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{2,40}$")


class TicketIdArgs(BaseModel):
    ticket_id: str = Field(pattern=r"^tkt_[0-9a-f]{10}$")
    note: str = Field(default="", max_length=1000)


class UpdateArgs(BaseModel):
    ticket_id: str = Field(pattern=r"^tkt_[0-9a-f]{10}$")
    status: Literal["open", "in_progress", "closed", "rejected"]
    comment: str = Field(default="", max_length=1000)


class ListArgs(BaseModel):
    status: str | None = Field(default=None, pattern=r"^[a-z_]{3,20}$")


def build_server(
    store: TicketStore | None = None,
    *,
    tokens: dict[str, Principal] | None = None,
    default_principal: Principal | None = None,
    audit: AuditLog | None = None,
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8103,
) -> FastMCP:
    store = store or TicketStore()
    guard = Guard(NAME, audit or AuditLog(), default_principal)
    mcp = make_server(
        NAME,
        "File and track remediation tickets. High-priority tickets need "
        "approval by a different person.",
        tokens or {},
        http=http,
        host=host,
        port=port,
    )

    @mcp.tool()
    def create_ticket(
        title: str, body: str = "", priority: str = "medium", tenant_id: str | None = None
    ) -> dict[str, Any]:
        """Create a ticket. priority: low | medium | high (high requires approval)."""

        def run(p: Principal, a: CreateArgs) -> dict[str, Any]:
            tenant = p.tenant_id
            if a.tenant_id and a.tenant_id != p.tenant_id:
                if not p.has("tickets:cross_tenant"):
                    raise PermissionError("filing for another tenant requires tickets:cross_tenant")
                tenant = a.tenant_id
            status = "pending_approval" if a.priority == "high" else "open"
            t = store.add(
                Ticket(
                    "tkt_" + uuid.uuid4().hex[:10],
                    tenant,
                    a.title,
                    a.body,
                    a.priority,
                    p.name,
                    status,
                    history=[_event(p.name, "create")],
                )
            )
            return {"ticket_id": t.id, **t.view()}

        return guard.run(
            "create_ticket",
            "tickets:write",
            CreateArgs,
            {"title": title, "body": body, "priority": priority, "tenant_id": tenant_id},
            run,
        )

    @mcp.tool()
    def approve_ticket(ticket_id: str, note: str = "") -> dict[str, Any]:
        """Approve a pending high-priority ticket. Creators cannot approve their own tickets."""

        def run(p: Principal, a: TicketIdArgs) -> dict[str, Any]:
            t = store.get(p, a.ticket_id)
            if t.status != "pending_approval":
                raise ValueError(f"ticket is {t.status}, not pending_approval")
            if t.created_by == p.name:
                raise PermissionError("separation of duties: creator cannot approve")
            t.status, t.approved_by = "open", p.name
            t.history.append(_event(p.name, "approve", a.note))
            return t.view()

        return guard.run(
            "approve_ticket",
            "tickets:approve",
            TicketIdArgs,
            {"ticket_id": ticket_id, "note": note},
            run,
        )

    @mcp.tool()
    def update_ticket(ticket_id: str, status: str, comment: str = "") -> dict[str, Any]:
        """Move a ticket through open -> in_progress -> closed (or reject a pending one)."""

        def run(p: Principal, a: UpdateArgs) -> dict[str, Any]:
            t = store.get(p, a.ticket_id)
            if a.status not in TRANSITIONS[t.status]:
                raise ValueError(f"illegal transition {t.status} -> {a.status}")
            if a.status == "rejected" and not p.has("tickets:approve"):
                raise PermissionError("rejecting requires tickets:approve")
            t.status = a.status
            t.history.append(_event(p.name, f"status:{a.status}", a.comment))
            return t.view()

        return guard.run(
            "update_ticket",
            "tickets:write",
            UpdateArgs,
            {"ticket_id": ticket_id, "status": status, "comment": comment},
            run,
        )

    @mcp.tool()
    def get_ticket(ticket_id: str) -> dict[str, Any]:
        """Read one ticket with its history."""
        return guard.run(
            "get_ticket",
            "tickets:read",
            TicketIdArgs,
            {"ticket_id": ticket_id},
            lambda p, a: store.get(p, a.ticket_id).view(),
        )

    @mcp.tool()
    def list_tickets(status: str | None = None) -> dict[str, Any]:
        """List the caller's tenant tickets, optionally filtered by status."""
        return guard.run(
            "list_tickets",
            "tickets:read",
            ListArgs,
            {"status": status},
            lambda p, a: {
                "tickets": [
                    {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
                    for t in store.list(p, a.status)
                ]
            },
        )

    return mcp
