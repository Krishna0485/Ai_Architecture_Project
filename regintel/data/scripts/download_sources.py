"""Download public-domain US federal regulations from the eCFR API.

    python data/scripts/download_sources.py            # full parts -> data/raw/
    python data/scripts/download_sources.py --sample   # trimmed sample -> data/samples/ecfr/

US government works are not subject to copyright (17 U.S.C. 105); see docs/data-sources.md.
The eCFR API requires a compressed response (Accept-Encoding: gzip).
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
API = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml"


@dataclass(frozen=True)
class Source:
    source: str
    title: int
    part: int
    act: str
    citation: str
    effective_date: str
    sample_sections: tuple[str, ...]  # empty = whole part


SOURCES: list[Source] = [
    Source("16cfr314", 16, 314, "GLBA Safeguards Rule", "16 CFR Part 314", "2024-06-01", ()),
    Source(
        "29cfr825",
        29,
        825,
        "Family and Medical Leave Act (FMLA)",
        "29 CFR Part 825",
        "2024-06-01",
        (
            "825.100",
            "825.104",
            "825.110",
            "825.112",
            "825.113",
            "825.120",
            "825.200",
            "825.202",
            "825.207",
            "825.209",
            "825.214",
            "825.220",
            "825.300",
            "825.302",
            "825.500",
        ),
    ),
    Source(
        "12cfr1002",
        12,
        1002,
        "Equal Credit Opportunity Act (Regulation B)",
        "12 CFR Part 1002",
        "2024-06-01",
        (
            "1002.1",
            "1002.4",
            "1002.5",
            "1002.6",
            "1002.7",
            "1002.9",
            "1002.12",
            "1002.13",
            "1002.14",
        ),
    ),
]


def fetch(src: Source, client: httpx.Client) -> bytes:
    url = API.format(date=src.effective_date, title=src.title)
    resp = client.get(url, params={"part": src.part}, headers={"Accept-Encoding": "gzip"})
    resp.raise_for_status()
    return resp.content


def trim(xml_bytes: bytes, keep: tuple[str, ...]) -> bytes:
    """Keep only the selected DIV8 sections (and their DIV6 subpart wrappers)."""
    root = ET.fromstring(xml_bytes)  # noqa: S314 - trusted government source
    if not keep:
        return xml_bytes
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == "DIV8" and child.get("N") not in keep:
                parent.remove(child)
            elif child.tag in ("DIV9", "AUTH", "SOURCE"):
                parent.remove(child)
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == "DIV6" and child.find(".//DIV8") is None:
                parent.remove(child)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def manifest_entry(src: Source, file: str) -> dict[str, object]:
    return {
        "file": file,
        "source": src.source,
        "act": src.act,
        "citation": src.citation,
        "jurisdiction": "US-FED",
        "effective_date": src.effective_date,
        "version": "eCFR",
        "url": f"https://www.ecfr.gov/current/title-{src.title}/part-{src.part}",
        "licence": "US Government work - public domain (17 U.S.C. 105)",
        "tenant_id": "public",
        "allowed_groups": ["*"],
        "doc_type": "regulation",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample", action="store_true", help="write trimmed sample to data/samples"
    )
    args = parser.parse_args(argv)
    out_dir = ROOT / "data" / ("samples" if args.sample else "raw")
    (out_dir / "ecfr").mkdir(parents=True, exist_ok=True)
    entries = []
    with httpx.Client(timeout=120, headers={"User-Agent": "regintel-data-downloader"}) as client:
        for src in SOURCES:
            raw = fetch(src, client)
            data = trim(raw, src.sample_sections) if args.sample else raw
            rel = f"ecfr/{src.source}.xml"
            (out_dir / rel).write_bytes(data)
            entries.append(manifest_entry(src, rel))
            print(f"{src.citation}: {len(data):,} bytes -> {out_dir / rel}")
    manifest = out_dir / "sources.yaml"
    existing = yaml.safe_load(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    others = [
        e
        for e in (existing or {}).get("sources", [])
        if not str(e.get("file", "")).startswith("ecfr/")
    ]
    manifest.write_text(
        yaml.safe_dump({"sources": entries + others}, sort_keys=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
