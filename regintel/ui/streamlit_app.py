"""RegIntel demo UI (Streamlit). Run: ``make ui`` with the API on :8080 (``make dev``).

Tabs: Ask (cited answers with a source panel), Check a document (multi-agent check with human
review), Checklist (regulation section -> checklist + generated tests).
"""

from __future__ import annotations

import os
import time

import httpx
import streamlit as st

API = os.getenv("REGINTEL_UI_API", "http://localhost:8080")
st.set_page_config(page_title="RegIntel", page_icon="⚖️", layout="wide")
st.title("RegIntel - compliance intelligence")
key = st.sidebar.text_input(
    "API key", value=os.getenv("REGINTEL_UI_API_KEY", "dev-key-acme"), type="password"
)
H = {"X-API-Key": key}
st.sidebar.caption("Answers are informational, not legal advice.")
ask_tab, check_tab, checklist_tab = st.tabs(["Ask", "Check a document", "Checklist"])

with ask_tab:
    q = st.text_input("Question", "When must the FTC be notified of a notification event?")
    if st.button("Ask", type="primary") and q:
        r = httpx.post(f"{API}/v1/ask", json={"question": q}, headers=H, timeout=120)
        if r.status_code != 200:
            st.error(r.text)
        else:
            a = r.json()
            left, right = st.columns([3, 2])
            with left:
                if a["abstained"]:
                    st.warning(a["answer"])
                else:
                    st.markdown(a["answer"])
                st.caption(
                    f"confidence {a['confidence']:.2f} - {a['latency_ms']:.0f} ms - "
                    f"{'cached' if a['cached'] else a['model']}"
                )
            with right:
                st.subheader("Sources")
                for c in a["citations"]:
                    label = f"[{c['n']}] § {c['section']} {c['title']}"
                    st.markdown(f"[{label}]({c['url']})" if c["url"] else label)

with check_tab:
    up = st.file_uploader("Policy document (.md / .txt)", type=["md", "txt"])
    if up and st.button("Run compliance check", type="primary"):
        doc = httpx.post(
            f"{API}/v1/documents",
            headers=H,
            timeout=60,
            json={"filename": up.name, "text": up.read().decode("utf-8")},
        ).json()
        if doc.get("injection_signals"):
            st.warning(f"Injection signals in upload: {doc['injection_signals']} (quarantined)")
        chk = httpx.post(
            f"{API}/v1/checks", headers=H, json={"document_id": doc["document_id"]}, timeout=60
        ).json()
        st.session_state["check_id"] = chk["check_id"]
    cid = st.session_state.get("check_id")
    if cid:
        view = httpx.get(f"{API}/v1/checks/{cid}", headers=H, timeout=60).json()
        while view["status"] in ("queued", "running"):
            time.sleep(1)
            view = httpx.get(f"{API}/v1/checks/{cid}", headers=H, timeout=60).json()
        st.write(f"**{cid}** - {view['doc_type']} - status `{view['status']}`")
        rows = view["report"]["findings"] if view.get("report") else view["findings"]
        st.dataframe(
            [
                {k: f[k] for k in ("id", "requirement_id", "status", "severity", "rationale")}
                for f in rows
            ],
            use_container_width=True,
        )
        if view["status"] == "awaiting_review":
            gaps = [f["id"] for f in rows if f["status"] != "compliant"]
            fix = st.multiselect("Mark as accepted (partial)", gaps)
            if st.button("Approve findings"):
                body = {
                    "decision": "correct" if fix else "approve",
                    "corrections": [
                        {"finding_id": f, "status": "partial", "note": "accepted by reviewer"}
                        for f in fix
                    ],
                }
                httpx.post(f"{API}/v1/checks/{cid}/review", headers=H, json=body, timeout=120)
                st.rerun()

with checklist_tab:
    sec = st.text_input("Section", "314.4")
    if st.button("Generate checklist + tests"):
        r = httpx.post(f"{API}/v1/checklists", headers=H, json={"section_id": sec}, timeout=120)
        if r.status_code != 200:
            st.error(r.text)
        else:
            res = r.json()
            for item, test in zip(res["checklist"], res["tests"], strict=False):
                with st.expander(f"{item['id']}: {item['requirement'][:90]}"):
                    st.write(item["evidence_needed"])
                    st.code(test["pytest"], language="python")
                    st.code(test["gherkin"], language="gherkin")
