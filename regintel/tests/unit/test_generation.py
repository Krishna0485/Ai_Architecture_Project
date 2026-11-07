from __future__ import annotations

from pathlib import Path

import pytest

from regintel.cache.base import InMemoryCache
from regintel.cache.semantic import SemanticCache
from regintel.config import Settings
from regintel.container import Container, build_container
from regintel.generation.answer import ABSTAIN_TEXT, AnswerService
from regintel.generation.compression import compress_context
from regintel.generation.prompts import PromptNotFoundError, PromptRegistry
from regintel.llm.base import LLMRequest
from regintel.llm.budget import TokenBudget
from regintel.llm.gateway import LLMGateway
from regintel.llm.routing import RoutingPolicy
from regintel.retrieval.base import Chunk, ScoredChunk, SecurityContext
from regintel.retrieval.embeddings import HashingEmbedder
from tests.fixtures.fakes import ScriptedProvider

CTX = SecurityContext("acme", ("compliance",))


def test_prompt_registry_loads_all_prompts(settings: Settings) -> None:
    reg = PromptRegistry(settings.prompts_dir)
    ids = reg.ids()
    assert {"answer.v1", "answer.v2", "compare.v1", "extract_facts.v1"} <= set(ids)
    for pid in ids:
        tpl = reg.get(pid)
        assert tpl.user and tpl.task
    system, user = reg.render("answer.v1", question="Q?", context="CTX")
    assert "untrusted" in system and "Q?" in user and "CTX" in user
    with pytest.raises(KeyError):
        reg.render("answer.v1", question="only")
    with pytest.raises(PromptNotFoundError):
        reg.get("nope.v9")


def test_prompt_registry_validates_files(tmp_path: Path) -> None:
    (tmp_path / "bad.v1.md").write_text("no front matter", encoding="utf-8")
    (tmp_path / "wrong.v1.md").write_text("---\nid: other.v1\n---\n## user\nx", encoding="utf-8")
    (tmp_path / "nouser.v1.md").write_text(
        "---\nid: nouser.v1\n---\n## system\nx", encoding="utf-8"
    )
    reg = PromptRegistry(tmp_path)
    for pid in ("bad.v1", "wrong.v1", "nouser.v1"):
        with pytest.raises(ValueError):
            reg.get(pid)


def sc(cid: str, text: str, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(Chunk(cid, text, {"section": cid}), score)


def test_compression_dedupes_and_trims_to_budget() -> None:
    long = "Head > Sec\n" + " ".join(f"Sentence {i} about encryption keys." for i in range(80))
    items = [
        sc("a", "Head > A\nEncryption at rest is required."),
        sc("a2", "Head > A\nEncryption at rest is required."),  # duplicate
        sc("b", long),
    ]
    out = compress_context("encryption keys", items, budget_tokens=120)
    ids = [i.chunk.id for i in out]
    assert ids == ["a", "b"] and out[1].chunk.text.endswith("[compressed]")
    assert compress_context("x", items, budget_tokens=5) == []


def test_answer_service_cites_real_chunks(container: Container) -> None:
    a = container.answers.answer(
        "How many workweeks of FMLA leave is an employee entitled to?", CTX
    )
    assert not a.abstained and a.citations
    assert all(container.chunks.get(c.chunk_id) for c in a.citations)
    assert "12 workweeks" in a.answer
    assert a.usage["prompt_tokens"] > 0


def test_answer_service_abstains_out_of_scope(container: Container) -> None:
    a = container.answers.answer("Who won the football world cup in 2022?", CTX)
    assert a.abstained and a.answer == ABSTAIN_TEXT and not a.citations


def _service_with(container: Container, fn: object) -> AnswerService:
    gateway = LLMGateway(
        [(ScriptedProvider(fn), None)],
        RoutingPolicy(),  # type: ignore[arg-type]
        TokenBudget(100_000, 10**9),
        {},
    )
    return AnswerService(
        container.retrieval,
        gateway,
        container.prompts,
        container.redactor,
        container.scanner,
        idf=container.retrieval.term_weight,
        allowed_link_domains=["ecfr.gov"],
    )


def test_invented_citations_are_dropped_and_ungrounded_answers_abstain(
    container: Container,
) -> None:
    q = "How many workweeks of FMLA leave is an employee entitled to?"
    svc = _service_with(container, lambda r: "Twelve weeks [1] [9] see https://evil.example/x")
    a = svc.answer(q, CTX)
    assert [c.n for c in a.citations] == [1]
    assert "[9]" not in a.answer and "evil.example" not in a.answer
    svc = _service_with(container, lambda r: "Twelve weeks, trust me.")
    assert svc.answer(q, CTX).abstained


def test_answer_output_is_pii_redacted_and_html_escaped(container: Container) -> None:
    q = "How many workweeks of FMLA leave is an employee entitled to?"
    svc = _service_with(container, lambda r: "<script>x</script> mail bob@example.com [1]")
    a = svc.answer(q, CTX)
    assert "<script>" not in a.answer and "&lt;script&gt;" in a.answer
    assert "bob@example.com" not in a.answer


def test_question_pii_is_redacted_before_model(container: Container) -> None:
    seen: list[LLMRequest] = []

    def fn(r: LLMRequest) -> str:
        seen.append(r)
        return "Answer [1]"

    svc = _service_with(container, fn)
    svc.answer(
        "Employee 123-45-6789 asks: how many workweeks of FMLA leave is an employee entitled to?",
        CTX,
    )
    assert seen and "123-45-6789" not in seen[0].user


def test_streaming_yields_tokens_then_final(container: Container) -> None:
    events = list(container.answers.stream("How many workweeks of FMLA leave?", CTX))
    assert events[0]["type"] == "token" and events[-1]["type"] == "final"
    assert events[-1]["answer"]["citations"]
    out = list(container.answers.stream("capital of France?", CTX))
    assert out[-1]["answer"]["abstained"]


def test_semantic_cache_hit(settings: Settings, sample_chunks: list[Chunk]) -> None:
    s = settings.model_copy(update={"cache_backend": "memory"})
    c = build_container(s, chunks=sample_chunks)
    assert isinstance(c.semantic_cache, SemanticCache)
    q = "How many workweeks of FMLA leave is an employee entitled to?"
    first, second = c.answers.answer(q, CTX), c.answers.answer(q, CTX)
    assert not first.cached and second.cached and second.answer == first.answer
    other = SecurityContext("globex", ("compliance",))
    assert not c.answers.answer(q, other).cached  # namespaced per tenant


def test_semantic_cache_object() -> None:
    cache = SemanticCache(HashingEmbedder(64), InMemoryCache(), 0.99)
    assert cache.hit_rate == 0.0
