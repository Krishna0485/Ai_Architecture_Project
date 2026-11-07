from __future__ import annotations

from servers.checklist import ChecklistStore, build_server
from tests.conftest import call, call_error, connect, principal

WRITER = principal("ann", "acme", "checklist:read", "checklist:write")
OTHER = principal("bob", "acme", "checklist:read", "checklist:write")
GLOBEX = principal("gil", "globex", "checklist:read", "checklist:write")


async def test_checklist_lifecycle_and_rules() -> None:
    store = ChecklistStore()
    async with connect(build_server(store, default_principal=WRITER)) as c:
        cl = await call(
            c,
            "create_checklist",
            title="16 CFR 314.4",
            source="16cfr314",
            items=["Designate a qualified individual", "Implement MFA"],
        )
        cid = cl["id"]
        assert cl["progress"] == "0/2"
        assert "requires evidence" in await call_error(
            c, "set_item_status", checklist_id=cid, item_id="i2", status="done"
        )
        cl = await call(
            c,
            "set_item_status",
            checklist_id=cid,
            item_id="i2",
            status="done",
            evidence="IdP policy screenshot",
        )
        assert cl["progress"] == "1/2"
        cl = await call(c, "add_item", checklist_id=cid, text="Annual board report")
        assert len(cl["items"]) == 3
        assert "not found" in await call_error(
            c, "set_item_status", checklist_id=cid, item_id="i9", status="open"
        )
        assert "invalid arguments" in await call_error(
            c, "set_item_status", checklist_id=cid, item_id="i1", status="approved"
        )
        listed = await call(c, "list_checklists")
        assert [x["id"] for x in listed["checklists"]] == [cid]
    async with connect(build_server(store, default_principal=OTHER)) as c:
        assert "owner" in await call_error(c, "archive_checklist", checklist_id=cid)
    async with connect(build_server(store, default_principal=GLOBEX)) as c:
        assert "not found" in await call_error(c, "get_checklist", checklist_id=cid)
    async with connect(build_server(store, default_principal=WRITER)) as c:
        assert (await call(c, "archive_checklist", checklist_id=cid))["archived"] is True
        assert "archived" in await call_error(c, "add_item", checklist_id=cid, text="more stuff")
        assert (await call(c, "list_checklists"))["checklists"] == []


async def test_read_only_principal_cannot_write() -> None:
    reader = principal("rita", "acme", "checklist:read")
    async with connect(build_server(default_principal=reader)) as c:
        assert "permission denied" in await call_error(
            c, "create_checklist", title="x list", items=["a item"]
        )
