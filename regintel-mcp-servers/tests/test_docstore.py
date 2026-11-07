from __future__ import annotations

import json
from pathlib import Path

from servers.docstore import DocStore, Document, build_server
from shared.audit import AuditLog
from tests.conftest import call, call_error, connect, principal

DOCS = [
    Document("pub-1", "public", "GLBA overview", "Multi-factor authentication (MFA) is required."),
    Document(
        "acme-1",
        "acme",
        "Acme MFA standard",
        "Acme requires MFA for all admins.",
        groups=("security",),
    ),
    Document("acme-2", "acme", "Acme handbook", "Leave policy and MFA notes for staff."),
    Document("globex-1", "globex", "Globex secrets", "Globex MFA rollout plan."),
]


async def test_search_respects_tenant_and_groups() -> None:
    audit = AuditLog()
    reader = principal("ann", "acme", "docs:read")
    async with connect(build_server(DocStore(DOCS), default_principal=reader, audit=audit)) as c:
        ids = {r["id"] for r in (await call(c, "search_documents", query="MFA"))["results"]}
        assert ids == {"pub-1", "acme-2"}  # acme-1 needs group:security, globex-1 other tenant
        assert "not found" in await call_error(c, "fetch_document", doc_id="globex-1")
        assert "not found" in await call_error(c, "fetch_document", doc_id="acme-1")
        doc = await call(c, "fetch_document", doc_id="acme-2", max_chars=100)
        assert doc["title"] == "Acme handbook" and doc["truncated"] is False
        assert "invalid arguments" in await call_error(c, "search_documents", query="x")
        assert "invalid arguments" in await call_error(c, "fetch_document", doc_id="../etc")
    sec = principal("sam", "acme", "docs:read", "group:security")
    async with connect(build_server(DocStore(DOCS), default_principal=sec)) as c:
        ids = {r["id"] for r in (await call(c, "search_documents", query="MFA"))["results"]}
        assert "acme-1" in ids
    assert {e["decision"] for e in audit.events} >= {"allow", "error", "invalid"}


async def test_missing_scope_and_no_write_tools() -> None:
    nobody = principal("eve", "acme")
    async with connect(build_server(DocStore(DOCS), default_principal=nobody)) as c:
        assert "permission denied" in await call_error(c, "search_documents", query="MFA")
        names = {t.name for t in (await c.list_tools()).tools}
        assert names == {"search_documents", "fetch_document"}


def test_from_json(tmp_path: Path) -> None:
    p = tmp_path / "docs.json"
    p.write_text(
        json.dumps([{"id": "d1", "tenant_id": "t", "title": "T", "text": "x"}]), encoding="utf-8"
    )
    store = DocStore.from_json(p)
    assert store.get(principal("a", "t"), "d1").title == "T"
