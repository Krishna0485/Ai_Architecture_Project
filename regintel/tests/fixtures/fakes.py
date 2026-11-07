"""Test doubles: scripted LLM providers and tiny documents. No network anywhere."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from regintel.ingestion.models import Block, ParsedDocument, Section, SourceMetadata
from regintel.llm.base import LLMError, LLMRequest, LLMResponse, Usage


class ScriptedProvider:
    """Returns responses from a function of the request; records every call."""

    def __init__(self, fn: Callable[[LLMRequest], str], name: str = "scripted") -> None:
        self.fn = fn
        self.name = name
        self.calls: list[tuple[LLMRequest, str]] = []

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        self.calls.append((request, model))
        text = self.fn(request)
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )

    def stream(self, request: LLMRequest, model: str) -> Iterator[str]:
        yield from self.complete(request, model).text.split(" ")


class FailingProvider:
    name = "failing"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        self.calls += 1
        raise LLMError("boom")

    def stream(self, request: LLMRequest, model: str) -> Iterator[str]:
        raise LLMError("boom")
        yield ""  # pragma: no cover


def make_doc(
    sections: list[tuple[str, str, list[Block]]],
    source: str = "testdoc",
    tenant: str = "public",
    groups: list[str] | None = None,
) -> ParsedDocument:
    meta = SourceMetadata(
        source=source,
        act="Test Act",
        citation="T CFR 1",
        tenant_id=tenant,
        allowed_groups=groups or ["*"],
    )
    return ParsedDocument(
        meta=meta,
        title="Test Act",
        sections=[
            Section(sid, title, ["Test Act", f"§ {sid} {title}"], blocks)
            for sid, title, blocks in sections
        ],
    )


ECFR_XML = """<?xml version="1.0"?>
<DIV5 N="999" TYPE="PART">
<HEAD>PART 999&#x2014;TEST RULES</HEAD>
<DIV6 N="A" TYPE="SUBPART"><HEAD>Subpart A&#x2014;General</HEAD>
<DIV8 N="999.1" TYPE="SECTION"><HEAD>&#xA7; 999.1 Purpose.</HEAD>
<P>(a) This part sets standards for widgets.</P>
<P>(b) It applies to all widget makers.</P>
</DIV8>
<DIV8 N="999.2" TYPE="SECTION"><HEAD>&#xA7; 999.2 [Reserved]</HEAD></DIV8>
<DIV8 N="999.3" TYPE="SECTION"><HEAD>&#xA7; 999.3 Fees.</HEAD>
<P>Fees are set out below.</P>
<GPOTABLE><BOXHD><CHED>Item</CHED><CHED>Fee</CHED></BOXHD>
<ROW><ENT>Widget</ENT><ENT>$5</ENT></ROW></GPOTABLE>
</DIV8>
</DIV6>
</DIV5>
"""
