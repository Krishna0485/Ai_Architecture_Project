"""Build and validate evals/datasets/golden_qa.jsonl from golden_qa.source.yaml.

Validation: every answerable item's sections must exist in the corpus and its `evidence` phrase
must appear (whitespace-normalised, case-insensitive) in one of those sections.

    python evals/datasets/build_golden.py            # build + validate
    python evals/datasets/build_golden.py --template # also write a CSV template for new items
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from regintel.ingestion.pipeline import ingest_directory  # noqa: E402

HERE = Path(__file__).parent


def norm(s: str) -> str:
    return (
        re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()  # noqa: RUF001
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", action="store_true")
    args = ap.parse_args(argv)
    src = yaml.safe_load((HERE / "golden_qa.source.yaml").read_text(encoding="utf-8"))
    chunks = ingest_directory(ROOT / "data" / "samples")
    section_text: dict[str, str] = {}
    for c in chunks:
        key = f"{c.metadata['source']}:{c.section_id}"
        section_text[key] = section_text.get(key, "") + " " + c.text
    errors: list[str] = []
    rows = []
    for i, item in enumerate(src["items"], start=1):
        qid = f"q{i:03d}"
        answerable = item.get("a") is not None
        sections = item.get("sections", [])
        if answerable:
            missing = [s for s in sections if s not in section_text]
            if missing:
                errors.append(f"{qid}: unknown sections {missing}")
            elif not any(norm(item["evidence"]) in norm(section_text[s]) for s in sections):
                errors.append(f"{qid}: evidence not found in {sections}: {item['evidence']!r}")
        rows.append(
            {
                "id": qid,
                "question": item["q"],
                "reference_answer": item.get("a"),
                "relevant_sections": sections,
                "evidence": item.get("evidence"),
                "tags": item.get("tags", []),
                "answerable": answerable,
            }
        )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    out = HERE / "golden_qa.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} items ({sum(r['answerable'] for r in rows)} answerable) -> {out}")
    if args.template:
        with (HERE / "golden_qa_template.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "question",
                    "reference_answer",
                    "sections (source:section;...)",
                    "evidence (verbatim phrase)",
                    "tags (;-separated)",
                ]
            )
            w.writerow(
                [
                    "<question>",
                    "<answer written from the regulation text>",
                    "16cfr314:314.4",
                    "<exact phrase from that section>",
                    "glba;topic",
                ]
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
