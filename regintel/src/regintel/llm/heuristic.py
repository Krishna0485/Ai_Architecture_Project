"""Deterministic offline "model" used in lite mode and CI.

It is *not* an LLM: each task is a transparent, rule-based stand-in operating on the structured
``inputs`` that the real prompt was rendered from. This keeps unit tests, the eval gate and the
e2e agent tests hermetic and reproducible. Real runs set ``REGINTEL_LLM_PROVIDER=openai_compatible``
and go through the LiteLLM gateway to Ollama or a hosted model.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from typing import Any

from regintel.llm.base import LLMRequest, LLMResponse, Usage
from regintel.text import content_terms, count_tokens, sentences, slugify, terms

INSUFFICIENT = "INSUFFICIENT_CONTEXT"

# Domain abbreviations a small instruction-tuned model would expand when rewriting queries.
_EXPANSIONS: dict[str, str] = {
    "fmla": "family and medical leave",
    "glba": "gramm-leach-bliley safeguards customer information",
    "ecoa": "equal credit opportunity",
    "reg b": "equal credit opportunity regulation b",
    "mfa": "multi-factor authentication",
    "2fa": "multi-factor authentication",
    "ciso": "qualified individual information security program",
    "pto": "paid leave",
    "infosec": "information security",
    "pen test": "penetration testing",
    "pentest": "penetration testing",
    "vendor": "service provider",
    "vendors": "service providers",
    "breach": "notification event unauthorized acquisition",
    "fired": "discharge discriminate interfere",
    "maternity": "birth of a son or daughter",
    "paternity": "birth of a son or daughter",
}


def _strip_heading(text: str) -> str:
    lines = text.split("\n", 1)
    return lines[1] if len(lines) == 2 and " > " in lines[0] else text


def _answer(inputs: dict[str, Any]) -> str:
    question: str = inputs.get("question", "")
    contexts: list[dict[str, Any]] = inputs.get("contexts", [])
    weights: dict[str, float] = inputs.get("term_weights") or {}
    q_terms = content_terms(question)
    total = sum(weights.get(t, 1.0) for t in q_terms) or 1.0
    candidates: list[tuple[float, int, int, str]] = []
    for ctx in contexts:
        body = _strip_heading(str(ctx["text"]))
        for pos, sent in enumerate(sentences(body)):
            if len(sent) < 25:
                continue
            matched = q_terms & content_terms(sent)
            cov = sum(weights.get(t, 1.0) for t in matched) / total  # IDF-weighted coverage
            density = len(matched) / max(8, len(terms(sent))) * 4
            candidates.append((cov + 0.25 * density, int(ctx["n"]), pos, sent))
    candidates.sort(key=lambda c: c[0], reverse=True)
    picked = [c for c in candidates[:3] if c[0] >= 0.3]
    if not picked:
        return INSUFFICIENT
    # Keep the strongest sentence and any others close to it, in document order.
    best = picked[0][0]
    keep = sorted((c for c in picked if c[0] >= best * 0.75), key=lambda c: (c[1], c[2]))
    return " ".join(f"{s.rstrip()} [{n}]" for _, n, _, s in keep)


def _rewrite(inputs: dict[str, Any]) -> str:
    q = str(inputs.get("question", ""))
    low = q.lower()
    extra = [exp for abbr, exp in _EXPANSIONS.items() if re.search(rf"\b{re.escape(abbr)}\b", low)]
    return f"{q} {' '.join(extra)}".strip() if extra else q


_DOC_TYPES = {
    "information_security_policy": {"security", "encryption", "access", "customer", "incident"},
    "leave_policy": {"leave", "fmla", "employee", "medical", "eligible"},
    "credit_policy": {"credit", "applicant", "loan", "adverse", "underwriting"},
}


def _classify(inputs: dict[str, Any]) -> str:
    text = str(inputs.get("text", ""))
    words = content_terms(text)
    scores = {k: len(words & v) for k, v in _DOC_TYPES.items()}
    best = max(scores, key=scores.__getitem__)
    doc_type = best if scores[best] > 0 else "unknown"
    return json.dumps({"doc_type": doc_type, "confidence": min(1.0, scores.get(best, 0) / 5)})


def _extract_facts(inputs: dict[str, Any]) -> str:
    """Quarantined extraction: turn untrusted document text into policy statements only.
    Imperative instructions addressed to the AI are not policy statements and are dropped."""
    text = str(inputs.get("text", ""))
    statements: list[dict[str, str]] = []
    heading = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            heading = s.lstrip("# ").strip()
            continue
        for sent in sentences(s):
            if re.search(r"\b(ignore|disregard)\b.*\b(instruction|previous|above)", sent, re.I):
                continue
            if re.search(r"\b(assistant|ai model|language model|system prompt)\b", sent, re.I):
                continue
            statements.append({"topic": heading or "general", "statement": sent[:500]})
    return json.dumps({"statements": statements[:200]})


_NUM = re.compile(
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(hours?|days?|weeks?|workweeks?|months?|years?|employees?|miles?|consumers?)",
    re.I,
)


def _numbers(text: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for value, unit in _NUM.findall(text):
        u = unit.lower().rstrip("s")
        out.append((float(value.replace(",", "")), "week" if u == "workweek" else u))
    return out


def _compare(inputs: dict[str, Any]) -> str:
    """Decide if policy statements satisfy a requirement: keyword evidence + numeric constraint."""
    req: dict[str, Any] = inputs.get("requirement", {})
    stmts: list[str] = [str(s) for s in inputs.get("statements", [])]
    keywords: list[str] = [str(k).lower() for k in req.get("keywords", [])]
    pattern = req.get("prohibited_pattern")
    if pattern:
        violations = [s for s in stmts if re.search(str(pattern), s, re.I)]
        if violations:
            return json.dumps(
                {
                    "status": "gap",
                    "evidence": violations[:3],
                    "rationale": "Policy describes a practice the regulation prohibits.",
                }
            )
        return json.dumps(
            {
                "status": "compliant",
                "evidence": [],
                "rationale": "No statement indicates the prohibited practice.",
            }
        )
    evidence = [s for s in stmts if any(k in s.lower() for k in keywords)]
    constraint: dict[str, Any] | None = req.get("constraint")
    if not evidence:
        return json.dumps(
            {
                "status": "gap",
                "evidence": [],
                "rationale": "No policy statement addresses this requirement.",
            }
        )
    if constraint:
        unit = str(constraint["unit"]).rstrip("s")
        limit = float(constraint["value"])
        op = str(constraint["op"])
        values = [v for s in evidence for v, u in _numbers(s) if u == unit]
        if values:
            ok = all(v <= limit for v in values) if op == "max" else all(v >= limit for v in values)
            if not ok:
                return json.dumps(
                    {
                        "status": "gap",
                        "evidence": evidence[:3],
                        "rationale": f"Policy states {values} {unit}(s); "
                        f"requirement is {op} {limit:g}.",
                    }
                )
    return json.dumps(
        {
            "status": "compliant",
            "evidence": evidence[:3],
            "rationale": "Policy statement(s) address the requirement.",
        }
    )


def _checklist(inputs: dict[str, Any]) -> str:
    text = _strip_heading(str(inputs.get("section_text", "")))
    section = str(inputs.get("section_id", ""))
    items: list[dict[str, str]] = []
    for sent in sentences(text):
        if re.search(
            r"\b(must|shall|required|requires|may not|no later than|at least)\b", sent, re.I
        ):
            items.append(
                {
                    "id": f"{section}-{len(items) + 1}",
                    "requirement": sent[:400],
                    "evidence_needed": "Documented policy or procedure demonstrating: "
                    + sent[:120],
                }
            )
        if len(items) >= 12:
            break
    return json.dumps({"section_id": section, "items": items})


def _testgen(inputs: dict[str, Any]) -> str:
    items: list[dict[str, str]] = inputs.get("items", [])
    tests: list[dict[str, str]] = []
    for it in items:
        name = slugify(it["requirement"], 50)
        keywords = sorted(content_terms(it["requirement"]), key=len, reverse=True)[:3]
        pytest_code = (
            f"def test_{name}(policy_text: str) -> None:\n"
            f'    """{it["id"]}: {it["requirement"][:80]}"""\n'
            f"    assert all(k in policy_text.lower() for k in {keywords!r})\n"
        )
        gherkin = (
            f"Scenario: {it['id']} is satisfied\n"
            f"  Given the organisation's compliance policy\n"
            f"  When it is reviewed against requirement {it['id']}\n"
            f"  Then it documents: {it['requirement'][:100]}"
        )
        tests.append({"item_id": it["id"], "pytest": pytest_code, "gherkin": gherkin})
    return json.dumps({"tests": tests})


def _judge(inputs: dict[str, Any]) -> str:
    from regintel.text import token_f1

    f1 = token_f1(str(inputs.get("answer", "")), str(inputs.get("reference", "")))
    score = 5 if f1 > 0.6 else 4 if f1 > 0.45 else 3 if f1 > 0.3 else 2 if f1 > 0.15 else 1
    return json.dumps({"score": score, "reason": f"token-F1 proxy {f1:.2f}"})


_SKILLS: dict[str, Callable[[dict[str, Any]], str]] = {
    "answer": _answer,
    "query_rewrite": _rewrite,
    "classify_document": _classify,
    "extract_facts": _extract_facts,
    "compare": _compare,
    "checklist": _checklist,
    "testgen": _testgen,
    "judge": _judge,
}


class HeuristicProvider:
    name = "heuristic"

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        start = time.perf_counter()
        skill = _SKILLS.get(request.task)
        if skill is None:
            raise ValueError(f"heuristic provider has no skill for task {request.task!r}")
        text = skill(request.inputs)
        return LLMResponse(
            text=text,
            model=f"heuristic/{model}",
            provider=self.name,
            usage=Usage(
                prompt_tokens=count_tokens(request.system + request.user),
                completion_tokens=count_tokens(text),
            ),
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def stream(self, request: LLMRequest, model: str) -> Iterator[str]:
        text = self.complete(request, model).text
        yield from re.findall(r"\S+\s*", text)
