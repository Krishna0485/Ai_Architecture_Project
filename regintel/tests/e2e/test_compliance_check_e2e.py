"""End-to-end: upload synthetic policies with 3 known gaps each, run the multi-agent check through
the API, approve, and assert exactly the known gaps are reported."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from regintel.config import PROJECT_ROOT
from tests.conftest import ACME, synthetic

pytestmark = pytest.mark.e2e
CASES = [
    json.loads(line)
    for line in (PROJECT_ROOT / "evals/datasets/check_cases.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_known_gaps_are_found(client: TestClient, case: dict) -> None:  # type: ignore[type-arg]
    up = client.post(
        "/v1/documents",
        headers=ACME,
        json={"filename": case["document"], "text": synthetic(case["document"])},
    )
    cid = client.post(
        "/v1/checks", headers=ACME, json={"document_id": up.json()["document_id"]}
    ).json()["check_id"]
    view = client.get(f"/v1/checks/{cid}", headers=ACME).json()
    assert view["doc_type"] == case["doc_type"]
    found = {f["requirement_id"] for f in view["findings"] if f["status"] != "compliant"}
    assert found == set(case["expected_gaps"])
    for f in view["findings"]:
        assert f["regulation_citations"], f  # every finding cites regulation text
    final = client.post(
        f"/v1/checks/{cid}/review", headers=ACME, json={"decision": "approve"}
    ).json()
    assert final["status"] == "completed"
    assert final["report"]["summary"].get("gap", 0) == len(case["expected_gaps"])
