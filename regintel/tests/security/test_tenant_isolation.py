"""Cross-tenant isolation: retrieval, answers, documents, checks, audit."""

from __future__ import annotations

from fastapi.testclient import TestClient

from regintel.container import Container
from regintel.retrieval.base import SecurityContext
from regintel.retrieval.factory import NAMED_CONFIGS
from tests.conftest import ACME, GLOBEX, synthetic

ACME_CANARY = "ACME-CANARY-7731"
GLOBEX_CANARY = "GLOBEX-CANARY-4419"
PROBES = [
    "escalation code",
    "ACME-CANARY-7731",
    "GLOBEX-CANARY-4419",
    "internal guidance escalation risk committee",
    "adverse action escalations credit desk",
]


def test_no_retrieval_mode_returns_another_tenants_chunks(container: Container) -> None:
    acme = SecurityContext("acme", ("compliance",))
    globex = SecurityContext("globex", ("compliance",))
    for cfg in NAMED_CONFIGS.values():
        p = container.retrieval.with_config(cfg)
        for q in PROBES:
            assert all(h.chunk.tenant_id in ("public", "acme") for h in p.search_k(q, acme, 20))
            assert all(h.chunk.tenant_id in ("public", "globex") for h in p.search_k(q, globex, 20))


def test_group_permissions_within_a_tenant(container: Container) -> None:
    hr_only = SecurityContext("acme", ("hr",))
    hits = container.retrieval.search_k("ACME-CANARY-7731 escalation", hr_only, 20)
    assert all(h.chunk.metadata.get("source") != "acme_internal_guidance" for h in hits)


def test_answers_never_contain_foreign_canaries(client: TestClient) -> None:
    def leaked(body: dict, canary: str, foreign_source: str) -> bool:  # type: ignore[type-arg]
        # The question is echoed back verbatim, so only inspect what the system produced.
        produced = {k: v for k, v in body.items() if k != "question"}
        return canary in str(produced) or any(foreign_source in r for r in body["retrieved_ids"])

    for q in PROBES:
        r = client.post("/v1/ask", json={"question": q}, headers=GLOBEX).json()
        assert not leaked(r, ACME_CANARY, "acme_internal_guidance")
        r = client.post("/v1/ask", json={"question": q}, headers=ACME).json()
        assert not leaked(r, GLOBEX_CANARY, "globex_internal_guidance")
    own = client.post(
        "/v1/ask",
        json={"question": "What escalation code must be quoted for Acme safeguards exceptions?"},
        headers=ACME,
    ).json()
    assert ACME_CANARY in own["answer"]


def test_documents_and_checks_are_tenant_scoped(client: TestClient) -> None:
    doc = client.post(
        "/v1/documents",
        headers=ACME,
        json={"filename": "p.md", "text": synthetic("acme_infosec_policy_gaps.md")},
    ).json()
    assert (
        client.post(
            "/v1/checks", headers=GLOBEX, json={"document_id": doc["document_id"]}
        ).status_code
        == 404
    )
    check = client.post("/v1/checks", headers=ACME, json={"document_id": doc["document_id"]}).json()
    assert client.get(f"/v1/checks/{check['check_id']}", headers=GLOBEX).status_code == 404
    assert client.post(
        f"/v1/checks/{check['check_id']}/review", headers=GLOBEX, json={"decision": "approve"}
    ).status_code in (403, 404)


def test_audit_log_is_tenant_scoped(client: TestClient) -> None:
    client.post("/v1/ask", json={"question": "What is FMLA?"}, headers=ACME)
    rows = client.get("/v1/admin/audit", headers=ACME).json()
    assert rows and all(r["tenant_id"] == "acme" for r in rows)
    # globex key has no admin group
    assert client.get("/v1/admin/audit", headers=GLOBEX).status_code == 403
