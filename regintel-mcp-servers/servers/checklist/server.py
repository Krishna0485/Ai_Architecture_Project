"""checklist: create checklists and update item status.

Narrow write tools: there is no bulk delete and no "update anything" tool. Items can be added and
have their status changed; only the creator (or ``checklist:admin``) can archive a checklist.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from shared.audit import AuditLog
from shared.auth import Principal
from shared.toolkit import Guard, make_server

NAME = "checklist"
ItemStatus = Literal["open", "done", "not_applicable"]


@dataclass
class Item:
    id: str
    text: str
    status: str = "open"
    evidence: str = ""


@dataclass
class Checklist:
    id: str
    tenant_id: str
    owner: str
    title: str
    source: str = ""
    items: list[Item] = field(default_factory=list)
    archived: bool = False

    def view(self) -> dict[str, Any]:
        done = sum(i.status != "open" for i in self.items)
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "owner": self.owner,
            "archived": self.archived,
            "progress": f"{done}/{len(self.items)}",
            "items": [i.__dict__ for i in self.items],
        }


class ChecklistStore:
    def __init__(self) -> None:
        self._lists: dict[str, Checklist] = {}
        self._lock = threading.Lock()

    def create(self, p: Principal, title: str, source: str, items: list[str]) -> Checklist:
        cl = Checklist(
            "cl_" + uuid.uuid4().hex[:10],
            p.tenant_id,
            p.name,
            title,
            source,
            [Item(f"i{n}", t) for n, t in enumerate(items, start=1)],
        )
        with self._lock:
            self._lists[cl.id] = cl
        return cl

    def get(self, p: Principal, checklist_id: str) -> Checklist:
        cl = self._lists.get(checklist_id)
        if cl is None or cl.tenant_id != p.tenant_id:
            raise KeyError(f"checklist {checklist_id} not found")
        return cl

    def list(self, p: Principal) -> list[Checklist]:
        return [c for c in self._lists.values() if c.tenant_id == p.tenant_id and not c.archived]


class CreateArgs(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    source: str = Field(default="", max_length=120)
    items: list[str] = Field(min_length=1, max_length=50)


class AddItemArgs(BaseModel):
    checklist_id: str = Field(pattern=r"^cl_[0-9a-f]{10}$")
    text: str = Field(min_length=3, max_length=600)


class StatusArgs(BaseModel):
    checklist_id: str = Field(pattern=r"^cl_[0-9a-f]{10}$")
    item_id: str = Field(pattern=r"^i\d{1,3}$")
    status: ItemStatus
    evidence: str = Field(default="", max_length=1000)


class IdArgs(BaseModel):
    checklist_id: str = Field(pattern=r"^cl_[0-9a-f]{10}$")


class NoArgs(BaseModel):
    pass


def build_server(
    store: ChecklistStore | None = None,
    *,
    tokens: dict[str, Principal] | None = None,
    default_principal: Principal | None = None,
    audit: AuditLog | None = None,
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8102,
) -> FastMCP:
    store = store or ChecklistStore()
    guard = Guard(NAME, audit or AuditLog(), default_principal)
    mcp = make_server(
        NAME,
        "Create compliance checklists and track item status.",
        tokens or {},
        http=http,
        host=host,
        port=port,
    )

    @mcp.tool()
    def create_checklist(title: str, items: list[str], source: str = "") -> dict[str, Any]:
        """Create a checklist (1-50 items), e.g. from a RegIntel get_checklist result."""
        return guard.run(
            "create_checklist",
            "checklist:write",
            CreateArgs,
            {"title": title, "items": items, "source": source},
            lambda p, a: store.create(p, a.title, a.source, a.items).view(),
        )

    @mcp.tool()
    def add_item(checklist_id: str, text: str) -> dict[str, Any]:
        """Append one item to a checklist."""

        def run(p: Principal, a: AddItemArgs) -> dict[str, Any]:
            cl = store.get(p, a.checklist_id)
            if cl.archived:
                raise ValueError("checklist is archived")
            if len(cl.items) >= 50:
                raise ValueError("checklist is full (50 items)")
            cl.items.append(Item(f"i{len(cl.items) + 1}", a.text))
            return cl.view()

        return guard.run(
            "add_item",
            "checklist:write",
            AddItemArgs,
            {"checklist_id": checklist_id, "text": text},
            run,
        )

    @mcp.tool()
    def set_item_status(
        checklist_id: str, item_id: str, status: str, evidence: str = ""
    ) -> dict[str, Any]:
        """Set an item's status to open, done or not_applicable (with optional evidence)."""

        def run(p: Principal, a: StatusArgs) -> dict[str, Any]:
            cl = store.get(p, a.checklist_id)
            item = next((i for i in cl.items if i.id == a.item_id), None)
            if item is None:
                raise KeyError(f"item {a.item_id} not found")
            if a.status == "done" and not a.evidence:
                raise ValueError("marking an item done requires evidence")
            item.status, item.evidence = a.status, a.evidence
            return cl.view()

        return guard.run(
            "set_item_status",
            "checklist:write",
            StatusArgs,
            {
                "checklist_id": checklist_id,
                "item_id": item_id,
                "status": status,
                "evidence": evidence,
            },
            run,
        )

    @mcp.tool()
    def get_checklist(checklist_id: str) -> dict[str, Any]:
        """Read one checklist."""
        return guard.run(
            "get_checklist",
            "checklist:read",
            IdArgs,
            {"checklist_id": checklist_id},
            lambda p, a: store.get(p, a.checklist_id).view(),
        )

    @mcp.tool()
    def list_checklists() -> dict[str, Any]:
        """List active checklists for the caller's tenant."""
        return guard.run(
            "list_checklists",
            "checklist:read",
            NoArgs,
            {},
            lambda p, a: {
                "checklists": [
                    {"id": c.id, "title": c.title, "progress": c.view()["progress"]}
                    for c in store.list(p)
                ]
            },
        )

    @mcp.tool()
    def archive_checklist(checklist_id: str) -> dict[str, Any]:
        """Archive a checklist (owner or checklist:admin only). Archived lists are read-only."""

        def run(p: Principal, a: IdArgs) -> dict[str, Any]:
            cl = store.get(p, a.checklist_id)
            if cl.owner != p.name and not p.has("checklist:admin"):
                raise PermissionError("only the owner or an admin can archive")
            cl.archived = True
            return cl.view()

        return guard.run(
            "archive_checklist", "checklist:write", IdArgs, {"checklist_id": checklist_id}, run
        )

    return mcp
