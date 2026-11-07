"""API integration tests against the in-process stack (real sample corpus, offline model)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from regintel.container import Container
from tests.conftest import ACME

pytestmark = pytest.mark.integration

QUESTIONS = [
    ("How many hours of service must an employee have to be eligible for FMLA leave?", "825.110"),
    ("When must the FTC be notified of a notification event?", "314.4"),
    ("How long must a creditor retain records for consumer credit applications?", "1002.12"),
]


def test_health_ready_metrics(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready["status"] == "ready" and ready["chunks"] > 50
    r = client.get("/health", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert (
        client.get("/health", headers={"x-request-id": "bad id!"}).headers["x-request-id"]
        != "bad id!"
    )
    client.post("/v1/ask", headers=ACME, json={"question": QUESTIONS[0][0]})
    assert "regintel_request_seconds" in client.get("/metrics").text


@pytest.mark.parametrize(("question", "section"), QUESTIONS)
def test_ask_returns_citations_to_real_chunks(
    client: TestClient, container: Container, question: str, section: str
) -> None:
    r = client.post("/v1/ask", headers=ACME, json={"question": question})
    assert r.status_code == 200
    body = r.json()
    assert not body["abstained"] and body["citations"]
    for c in body["citations"]:
        assert container.chunks.get(c["chunk_id"]) is not None
    assert any(c["section"] == section for c in body["citations"])


def test_ask_with_metadata_filter(client: TestClient) -> None:
    r = client.post(
        "/v1/ask",
        headers=ACME,
        json={
            "question": "What notice must employers give?",
            "act": "Family and Medical Leave Act (FMLA)",
        },
    )
    assert all(c["source"] == "29cfr825" for c in r.json()["citations"])


def test_ask_stream_sse(client: TestClient) -> None:
    with client.stream(
        "POST", "/v1/ask/stream", headers=ACME, json={"question": QUESTIONS[0][0]}
    ) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "token" and events[-1]["type"] == "final"
    assert events[-1]["answer"]["citations"]


def test_check_review_and_checklist_flow(client: TestClient) -> None:
    from tests.conftest import synthetic

    up = client.post(
        "/v1/documents",
        headers=ACME,
        json={"filename": "leave.md", "text": synthetic("acme_leave_policy_gaps.md")},
    )
    assert up.status_code == 201
    started = client.post(
        "/v1/checks", headers=ACME, json={"document_id": up.json()["document_id"]}
    )
    assert started.status_code == 202
    cid = started.json()["check_id"]
    view = client.get(f"/v1/checks/{cid}", headers=ACME).json()
    assert view["status"] == "awaiting_review" and view["pending_review"]["open_items"] == 3
    gap = next(f for f in view["findings"] if f["status"] == "gap")
    done = client.post(
        f"/v1/checks/{cid}/review",
        headers=ACME,
        json={
            "decision": "correct",
            "corrections": [{"finding_id": gap["id"], "status": "partial"}],
        },
    )
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert (
        client.post(
            f"/v1/checks/{cid}/review", headers=ACME, json={"decision": "approve"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/v1/checks/{cid}/review",
            headers=ACME,
            json={"decision": "correct", "corrections": [{"finding_id": "F-1", "status": "gap"}]},
        ).status_code
        == 409
    )
    assert client.get("/v1/checks/chk_000000000000", headers=ACME).status_code == 404
    assert (
        client.post(
            "/v1/checks", headers=ACME, json={"document_id": "doc_000000000000"}
        ).status_code
        == 404
    )
    cl = client.post(
        "/v1/checklists", headers=ACME, json={"section_id": "825.110", "source": "29cfr825"}
    )
    assert cl.status_code == 200 and cl.json()["checklist"] and cl.json()["tests"]
    assert (
        client.post("/v1/checklists", headers=ACME, json={"section_id": "9999.9"}).status_code
        == 404
    )


def test_kill_switch_returns_503(container: Container) -> None:
    from regintel.api.main import create_app

    container.checks.enabled = False
    with TestClient(create_app(container=container)) as c:
        r = c.post("/v1/checklists", headers=ACME, json={"section_id": "825.110"})
        assert r.status_code == 503
        r = c.post("/v1/checks", headers=ACME, json={"document_id": "doc_000000000000"})
        assert r.status_code in (404, 503)
