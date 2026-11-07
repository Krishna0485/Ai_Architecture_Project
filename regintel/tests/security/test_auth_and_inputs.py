from __future__ import annotations

from fastapi.testclient import TestClient

from regintel.api.auth import resolve_api_key
from regintel.config import ApiKeyGrant
from tests.conftest import ACME


def test_requests_without_valid_key_are_rejected(client: TestClient) -> None:
    for headers in ({}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}):
        assert (
            client.post("/v1/ask", json={"question": "hello there"}, headers=headers).status_code
            == 401
        )


def test_tenant_comes_from_key_not_from_body(client: TestClient) -> None:
    r = client.post(
        "/v1/ask",
        headers=ACME,
        json={"question": "What is FMLA?", "tenant_id": "globex", "groups": ["admin"]},
    )
    assert r.status_code == 200
    audit = client.get("/v1/admin/audit", headers=ACME).json()
    assert audit[0]["tenant_id"] == "acme"


def test_input_validation(client: TestClient) -> None:
    assert client.post("/v1/ask", headers=ACME, json={"question": "x" * 5000}).status_code == 422
    assert (
        client.post("/v1/checks", headers=ACME, json={"document_id": "../etc/passwd"}).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/checklists", headers=ACME, json={"section_id": "314.4; rm -rf /"}
        ).status_code
        == 422
    )


def test_resolve_api_key() -> None:
    grants = {"k1": ApiKeyGrant(tenant_id="t", groups=["g"])}
    ctx = resolve_api_key("k1", grants, "rid")
    assert ctx is not None and ctx.tenant_id == "t" and ctx.request_id == "rid"
    assert resolve_api_key("k2", grants) is None and resolve_api_key(None, grants) is None
