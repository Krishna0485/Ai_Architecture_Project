from __future__ import annotations

from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from regintel.audit.models import AuditEvent
from regintel.audit.writer import InMemoryAuditWriter, JsonlAuditWriter, build_audit_writer
from regintel.config import Settings
from regintel.observability import tracing
from regintel.observability.langfuse import NoopTracer, build_tracer
from regintel.observability.metrics import LLM_TOKENS, render_latest
from regintel.storage.documents import DocumentRepository


def test_jsonl_audit_redacts_and_filters_by_tenant(tmp_path: Path) -> None:
    w = JsonlAuditWriter(tmp_path / "a.jsonl")
    w.write(
        AuditEvent(
            tenant_id="acme",
            actor="u",
            action="ask",
            details={"q": "mail jane@acme.example", "nested": [{"ssn": "123-45-6789"}]},
        )
    )
    w.write(AuditEvent(tenant_id="globex", actor="u", action="ask"))
    raw = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert "jane@acme.example" not in raw and "123-45-6789" not in raw
    rows = w.query("acme")
    assert len(rows) == 1 and rows[0].details["q"] == "mail <EMAIL>"
    assert JsonlAuditWriter(tmp_path / "x" / "none.jsonl").query("acme") == []


def test_memory_audit_and_factory(tmp_path: Path) -> None:
    m = InMemoryAuditWriter()
    m.write(AuditEvent(tenant_id="t", actor="a", action="x", details={"e": "a@b.co"}))
    assert m.query("t")[0].details["e"] == "<EMAIL>" and m.query("other") == []
    assert isinstance(build_audit_writer(Settings(audit_backend="memory")), InMemoryAuditWriter)
    assert isinstance(
        build_audit_writer(Settings(audit_path=tmp_path / "a.jsonl")), JsonlAuditWriter
    )


def test_document_repository_is_tenant_scoped_and_persistent(tmp_path: Path) -> None:
    repo = DocumentRepository(tmp_path)
    d = repo.add("acme", "p.md", "text body")
    assert repo.get(d.id, "acme") == d
    assert repo.get(d.id, "globex") is None
    assert DocumentRepository(tmp_path).get(d.id, "acme") is not None
    assert [x.id for x in repo.list("acme")] == [d.id]


def test_metrics_render() -> None:
    LLM_TOKENS.labels("answer", "smart", "prompt").inc(3)
    assert b"regintel_llm_tokens_total" in render_latest()


def test_tracing_with_in_memory_exporter() -> None:
    exporter = InMemorySpanExporter()
    tracing._configured = False
    assert tracing.setup_tracing(Settings(), exporter=exporter)
    with tracing.span("unit.test", foo="bar", n=1, skip=None):
        assert len(tracing.current_trace_id()) == 32
    from opentelemetry import trace

    trace.get_tracer_provider().force_flush()  # type: ignore[attr-defined]
    names = [s.name for s in exporter.get_finished_spans()]
    assert "unit.test" in names
    assert tracing.setup_tracing(Settings())  # idempotent


def test_langfuse_noop_by_default() -> None:
    t = build_tracer(Settings())
    assert isinstance(t, NoopTracer)
    t.record(name="x", model="m", input_text="i", output_text="o", usage={}, metadata={})
