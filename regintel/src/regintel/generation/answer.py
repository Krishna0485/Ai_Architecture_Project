"""Citation-grounded answer synthesis with abstention.

Citations are produced as ``[n]`` markers that index the numbered context we supplied; they are
mapped back to real chunk IDs and validated. The model can never invent a source.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from typing import Any

from pydantic import BaseModel, Field

from regintel.cache.semantic import SemanticCache
from regintel.guardrails import PIIRedactor, sanitize_text, validate_citations, wrap_untrusted
from regintel.guardrails.injection import InjectionScanner
from regintel.llm.base import LLMRequest
from regintel.llm.gateway import LLMGateway
from regintel.llm.heuristic import INSUFFICIENT
from regintel.observability import metrics
from regintel.observability.tracing import span
from regintel.retrieval.base import MetadataFilter, ScoredChunk, SecurityContext
from regintel.retrieval.factory import RetrievalPipeline
from regintel.text import content_terms

from .compression import compress_context
from .prompts import PromptRegistry

ABSTAIN_TEXT = "I don't have enough context in the indexed regulations to answer that reliably."
_CITE = re.compile(r"\[(\d{1,2})\]")
_PLACEHOLDER = re.compile(r"<[A-Z_]+>")  # PII redaction markers are not query terms


class Citation(BaseModel):
    n: int
    chunk_id: str
    source: str
    section: str
    title: str
    url: str = ""


class Answer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    confidence: float = 0.0
    retrieved_ids: list[str] = Field(default_factory=list)
    prompt_id: str = ""
    model: str = ""
    cached: bool = False
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
    quarantined_chunks: list[str] = Field(default_factory=list)


class AnswerService:
    def __init__(
        self,
        retrieval: RetrievalPipeline,
        gateway: LLMGateway,
        prompts: PromptRegistry,
        redactor: PIIRedactor,
        scanner: InjectionScanner,
        *,
        prompt_id: str = "answer.v1",
        min_score: float = 0.40,
        context_budget: int = 1800,
        compress: bool = True,
        max_output_tokens: int = 700,
        allowed_link_domains: list[str] | None = None,
        semantic_cache: SemanticCache | None = None,
        idf: Callable[[str], float] | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.gateway = gateway
        self.prompts = prompts
        self.redactor = redactor
        self.scanner = scanner
        self.prompt_id = prompt_id
        self.min_score = min_score
        self.context_budget = context_budget
        self.compress = compress
        self.max_output_tokens = max_output_tokens
        self.allowed_link_domains = allowed_link_domains or []
        self.semantic_cache = semantic_cache
        self.idf = idf

    def confidence(self, question: str, texts: list[str]) -> float:
        """IDF-weighted coverage of the question's terms by the best passage (0..1).

        Rare terms dominate: a question about "California" or "GDPR" scores low against a corpus
        that never mentions them, even if generic words ("minimum", "employers") match. Terms
        unseen in the corpus get the maximum weight."""
        q = content_terms(_PLACEHOLDER.sub(" ", question))
        if not q or not texts:
            return 0.0
        weights = {t: (self.idf(t) if self.idf else 1.0) for t in q}
        total = sum(weights.values()) or 1.0
        return max(
            sum(w for t, w in weights.items() if t in content_terms(text)) / total for text in texts
        )

    # -- helpers -------------------------------------------------------------------------
    def _prepare(
        self, question: str, ctx: SecurityContext, filters: MetadataFilter | None
    ) -> tuple[list[ScoredChunk], float, list[str]]:
        hits = self.retrieval.search(question, ctx, filters)
        quarantined: list[str] = []
        safe: list[ScoredChunk] = []
        for h in hits:  # indirect injection defence on retrieved content
            if self.scanner.scan(h.chunk.text).is_suspicious:
                quarantined.append(h.chunk.id)
                metrics.GUARDRAIL_BLOCKS.labels("injection", "quarantine_chunk").inc()
            else:
                safe.append(h)
        if self.compress:
            safe = compress_context(question, safe, self.context_budget)
        confidence = self.confidence(question, [h.chunk.text for h in safe[:3]])
        return safe, confidence, quarantined

    def _render(self, question: str, hits: list[ScoredChunk]) -> tuple[str, str, dict[str, Any]]:
        blocks = [
            f"[{i}] ({h.chunk.metadata.get('citation', '')} § {h.chunk.section_id})\n"
            + wrap_untrusted(h.chunk.text, h.chunk.id)
            for i, h in enumerate(hits, start=1)
        ]
        system, user = self.prompts.render(
            self.prompt_id, question=question, context="\n\n".join(blocks)
        )
        q_terms = content_terms(_PLACEHOLDER.sub(" ", question))
        inputs = {
            "question": question,
            "contexts": [{"n": i, "text": h.chunk.text} for i, h in enumerate(hits, 1)],
            "term_weights": {t: (self.idf(t) if self.idf else 1.0) for t in q_terms},
        }
        return system, user, inputs

    def _finalize(
        self, question: str, raw: str, hits: list[ScoredChunk], confidence: float
    ) -> tuple[str, list[Citation], bool]:
        if INSUFFICIENT in raw or not raw.strip():
            return ABSTAIN_TEXT, [], True
        by_n = {i: h for i, h in enumerate(hits, start=1)}
        cited_ns = [int(n) for n in _CITE.findall(raw)]
        valid_ids = set(
            validate_citations(
                [by_n[n].chunk.id for n in cited_ns if n in by_n], {h.chunk.id for h in hits}
            )
        )
        citations = []
        for n in dict.fromkeys(cited_ns):
            h = by_n.get(n)
            if h is None or h.chunk.id not in valid_ids:
                continue
            md = h.chunk.metadata
            citations.append(
                Citation(
                    n=n,
                    chunk_id=h.chunk.id,
                    source=md.get("source", ""),
                    section=h.chunk.section_id,
                    title=md.get("section_title", ""),
                    url=md.get("url", ""),
                )
            )
        # Remove markers that point at nothing we supplied.
        text = _CITE.sub(lambda m: m.group() if int(m.group(1)) in by_n else "", raw).strip()
        if not citations:  # an answer without valid grounding is not returned
            return ABSTAIN_TEXT, [], True
        return sanitize_text(text, self.redactor, self.allowed_link_domains), citations, False

    def _abstain(
        self,
        question: str,
        hits: list[ScoredChunk],
        confidence: float,
        quarantined: list[str],
        start: float,
    ) -> Answer:
        metrics.ABSTENTIONS.inc()
        return Answer(
            question=question,
            answer=ABSTAIN_TEXT,
            abstained=True,
            confidence=round(confidence, 3),
            retrieved_ids=[h.chunk.id for h in hits],
            prompt_id=self.prompt_id,
            quarantined_chunks=quarantined,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def _cache_ns(self, ctx: SecurityContext) -> str:
        return SemanticCache.namespace(ctx.tenant_id, self.prompt_id, self.retrieval.config.key)

    # -- public API ----------------------------------------------------------------------
    def answer(
        self, question: str, ctx: SecurityContext, filters: MetadataFilter | None = None
    ) -> Answer:
        start = time.perf_counter()
        question = self.redactor.redact(question).text  # never send raw PII to a model
        with span("generation.answer", prompt_id=self.prompt_id, tenant=ctx.tenant_id):
            if self.semantic_cache is not None and filters is None:
                hit = self.semantic_cache.lookup(self._cache_ns(ctx), question)
                if hit is not None:
                    cached = Answer.model_validate(hit.payload)
                    return cached.model_copy(
                        update={
                            "question": question,
                            "cached": True,
                            "latency_ms": (time.perf_counter() - start) * 1000,
                        }
                    )
            hits, confidence, quarantined = self._prepare(question, ctx, filters)
            if not hits or confidence < self.min_score:
                return self._abstain(question, hits, confidence, quarantined, start)
            system, user, inputs = self._render(question, hits)
            resp = self.gateway.complete(
                LLMRequest(
                    task="answer",
                    prompt_id=self.prompt_id,
                    system=system,
                    user=user,
                    inputs=inputs,
                    max_tokens=self.max_output_tokens,
                    tenant_id=ctx.tenant_id,
                )
            )
            text, citations, abstained = self._finalize(question, resp.text, hits, confidence)
            if abstained:
                return self._abstain(question, hits, confidence, quarantined, start)
            result = Answer(
                question=question,
                answer=text,
                citations=citations,
                abstained=False,
                confidence=round(confidence, 3),
                retrieved_ids=[h.chunk.id for h in hits],
                prompt_id=self.prompt_id,
                model=resp.model,
                usage={
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                },
                latency_ms=(time.perf_counter() - start) * 1000,
                quarantined_chunks=quarantined,
            )
            if self.semantic_cache is not None and filters is None:
                self.semantic_cache.store(self._cache_ns(ctx), question, result.model_dump())
            return result

    def stream(
        self, question: str, ctx: SecurityContext, filters: MetadataFilter | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield events: {"type":"token"} ... then a final {"type":"final","answer":Answer}."""
        start = time.perf_counter()
        question = self.redactor.redact(question).text
        hits, confidence, quarantined = self._prepare(question, ctx, filters)
        if not hits or confidence < self.min_score:
            final = self._abstain(question, hits, confidence, quarantined, start)
            yield {"type": "token", "text": final.answer}
            yield {"type": "final", "answer": final.model_dump()}
            return
        system, user, inputs = self._render(question, hits)
        produced: list[str] = []
        for token in self.gateway.stream(
            LLMRequest(
                task="answer",
                prompt_id=self.prompt_id,
                system=system,
                user=user,
                inputs=inputs,
                max_tokens=self.max_output_tokens,
                tenant_id=ctx.tenant_id,
                cacheable=False,
            )
        ):
            produced.append(token)
            yield {
                "type": "token",
                "text": sanitize_text(token, self.redactor, self.allowed_link_domains),
            }
        text, citations, abstained = self._finalize(question, "".join(produced), hits, confidence)
        final = Answer(
            question=question,
            answer=text,
            citations=citations,
            abstained=abstained,
            confidence=round(confidence, 3),
            retrieved_ids=[h.chunk.id for h in hits],
            prompt_id=self.prompt_id,
            quarantined_chunks=quarantined,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        yield {"type": "final", "answer": final.model_dump()}
