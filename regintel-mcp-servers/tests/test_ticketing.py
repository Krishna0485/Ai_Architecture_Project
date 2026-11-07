from __future__ import annotations

from servers.ticketing_mock import TicketStore, build_server
from shared.audit import AuditLog
from tests.conftest import call, call_error, connect, principal

AGENT = principal("regintel-agent", "acme", "tickets:write", "tickets:read")
SERVICE = principal(
    "regintel-svc", "regintel", "tickets:write", "tickets:read", "tickets:cross_tenant"
)
MANAGER = principal("maria", "acme", "tickets:read", "tickets:write", "tickets:approve")


async def test_high_priority_requires_approval_by_someone_else() -> None:
    store, audit = TicketStore(), AuditLog()
    async with connect(build_server(store, default_principal=AGENT, audit=audit)) as c:
        t = await call(c, "create_ticket", title="GLBA-MFA gap", body="no MFA", priority="high")
        tid = t["ticket_id"]
        assert t["status"] == "pending_approval"
        assert "permission denied" in await call_error(c, "approve_ticket", ticket_id=tid)
        assert "illegal transition" in await call_error(
            c, "update_ticket", ticket_id=tid, status="in_progress"
        )
    self_approver = principal("regintel-agent", "acme", "tickets:approve", "tickets:read")
    async with connect(build_server(store, default_principal=self_approver)) as c:
        assert "separation of duties" in await call_error(c, "approve_ticket", ticket_id=tid)
    async with connect(build_server(store, default_principal=MANAGER)) as c:
        t = await call(c, "approve_ticket", ticket_id=tid, note="go")
        assert t["status"] == "open" and t["approved_by"] == "maria"
        assert "not pending" in await call_error(c, "approve_ticket", ticket_id=tid)
        t = await call(c, "update_ticket", ticket_id=tid, status="in_progress", comment="started")
        t = await call(c, "update_ticket", ticket_id=tid, status="closed")
        assert [h["action"] for h in t["history"]] == [
            "create",
            "approve",
            "status:in_progress",
            "status:closed",
        ]
        assert "illegal" in await call_error(c, "update_ticket", ticket_id=tid, status="open")
    assert any(e["decision"] == "deny" for e in audit.events)


async def test_cross_tenant_requires_scope_and_isolation() -> None:
    store = TicketStore()
    async with connect(build_server(store, default_principal=AGENT)) as c:
        assert "cross_tenant" in await call_error(
            c, "create_ticket", title="spoof attempt", tenant_id="globex"
        )
        own = await call(c, "create_ticket", title="same tenant ok", tenant_id="acme")
        assert own["tenant_id"] == "acme" and own["status"] == "open"
    async with connect(build_server(store, default_principal=SERVICE)) as c:
        t = await call(
            c, "create_ticket", title="filed for globex", tenant_id="globex", priority="low"
        )
        assert t["tenant_id"] == "globex"
    globex = principal("gil", "globex", "tickets:read", "tickets:write")
    async with connect(build_server(store, default_principal=globex)) as c:
        listed = await call(c, "list_tickets")
        assert [x["title"] for x in listed["tickets"]] == ["filed for globex"]
        assert "not found" in await call_error(c, "get_ticket", ticket_id=own["ticket_id"])
        assert (await call(c, "list_tickets", status="closed"))["tickets"] == []


async def test_reject_requires_approver() -> None:
    store = TicketStore()
    async with connect(build_server(store, default_principal=AGENT)) as c:
        tid = (await call(c, "create_ticket", title="risky change", priority="high"))["ticket_id"]
        assert "requires tickets:approve" in await call_error(
            c, "update_ticket", ticket_id=tid, status="rejected"
        )
    async with connect(build_server(store, default_principal=MANAGER)) as c:
        assert (await call(c, "update_ticket", ticket_id=tid, status="rejected"))[
            "status"
        ] == "rejected"
