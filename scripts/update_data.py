#!/usr/bin/env python3
"""Generate static JSON for the investor dashboard.

The script intentionally uses only the Python standard library so it can run in
GitHub Actions without dependency installation.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "InvestReport.md"
SOURCES_PATH = ROOT / "data" / "sources.json"
ADDITIONAL_INVESTORS_PATH = ROOT / "data" / "additional-investors.json"
STATUS_PATH = ROOT / "data" / "source-status.json"
OUTPUT_PATH = ROOT / "data" / "site-data.json"


def clean_markdown(value: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = value.replace("<br>", " ")
    value = re.sub(r"\s+", " ", value)
    return html.unescape(value).strip()


def read_report() -> str:
    if not REPORT_PATH.exists():
        raise FileNotFoundError(f"Missing report: {REPORT_PATH}")
    return REPORT_PATH.read_text(encoding="utf-8")


def section_between(markdown: str, heading: str, next_level: str = "## ") -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(rf"^{re.escape(next_level)}", markdown[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(markdown)
    return markdown[start:end].strip()


def bullets(block: str) -> list[str]:
    output: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        if line.startswith("- "):
            if current:
                output.append(clean_markdown(" ".join(current)))
            current = [line[2:].strip()]
        elif current and line.strip() and not line.startswith("#"):
            current.append(line.strip())
        elif current:
            output.append(clean_markdown(" ".join(current)))
            current = []
    if current:
        output.append(clean_markdown(" ".join(current)))
    return [item for item in output if item]


def parse_tables(markdown: str) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    current_heading = "Unsorted"
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("### "):
            current_heading = clean_markdown(line[4:])
        elif line.startswith("## "):
            current_heading = clean_markdown(line[3:])

        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1]):
            headers = [clean_markdown(cell) for cell in line.strip("|").split("|")]
            rows: list[dict[str, str]] = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                values = [clean_markdown(cell) for cell in lines[i].strip("|").split("|")]
                if len(values) < len(headers):
                    values += [""] * (len(headers) - len(values))
                rows.append(dict(zip(headers, values)))
                i += 1
            tables[current_heading] = rows
            continue
        i += 1
    return tables


def parse_key_findings(markdown: str, tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    block = section_between(markdown, "## Key Findings")
    findings: list[dict[str, str]] = []
    matches = list(re.finditer(r"^###\s+(.+)$", block, re.MULTILINE))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        title = clean_markdown(match.group(1))
        preview = " ".join(bullets(block[start:end])[:2])
        if not preview:
            preview = clean_markdown(block[start:end].split("\n\n", 1)[0])
        if not preview and title in tables:
            names = []
            for row in tables[title][:4]:
                names.append(row.get("Fond") or row.get("Angel") or row.get("Subjekt") or row.get("Program") or "")
            names = [name for name in names if name]
            preview = f"Tabulkový přehled: {', '.join(names)}" if names else f"{len(tables[title])} položek v tabulce."
        findings.append({"title": title, "preview": textwrap.shorten(preview, width=420, placeholder="...")})
    return findings


def parse_action_plan(markdown: str) -> list[dict[str, Any]]:
    block = section_between(markdown, "## Recommendations")
    phases: list[dict[str, Any]] = []
    matches = list(re.finditer(r"^\*\*(Fáze[^*]+)\*\*", block, re.MULTILINE))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        phase_block = block[start:end]
        items = []
        for line in phase_block.splitlines():
            numbered = re.match(r"^\d+\.\s+(.*)$", line.strip())
            if numbered:
                items.append(clean_markdown(numbered.group(1)))
        phases.append({"title": clean_markdown(match.group(1)), "items": items})
    return phases


def extract_title_and_meta(markdown: str) -> tuple[str, str]:
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    meta_match = re.search(r"^\*\*Datum:\*\*\s+(.+)$", markdown, re.MULTILINE)
    title = clean_markdown(title_match.group(1)) if title_match else "Investor Mapping"
    meta = clean_markdown(meta_match.group(1)) if meta_match else ""
    return title, meta


def page_metadata(body: str) -> dict[str, str]:
    body = body[:250_000]
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    description_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not description_match:
        description_match = re.search(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
            body,
            re.IGNORECASE | re.DOTALL,
        )
    return {
        "title": clean_markdown(re.sub(r"<[^>]+>", " ", title_match.group(1))) if title_match else "",
        "description": clean_markdown(description_match.group(1)) if description_match else "",
    }


def stable_fingerprint(body: str) -> str:
    compact = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", body, flags=re.IGNORECASE | re.DOTALL)
    compact = re.sub(r"<[^>]+>", " ", compact)
    compact = clean_markdown(compact).lower()
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def fetch_source(source: dict[str, str], previous: dict[str, Any]) -> dict[str, Any]:
    headers = {
        "User-Agent": "PrautInvestorRadar/1.0 (+https://github.com/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    request = Request(source["url"], headers=headers)
    now = datetime.now(timezone.utc).isoformat()
    result = {
        **source,
        "checked_at": now,
        "status": None,
        "final_url": source["url"],
        "title": "",
        "description": "",
        "content_hash": "",
        "changed": False,
        "error": "",
    }
    try:
        with urlopen(request, timeout=8) as response:
            body_bytes = response.read(750_000)
            charset = response.headers.get_content_charset() or "utf-8"
            body = body_bytes.decode(charset, errors="replace")
            digest = stable_fingerprint(body)
            meta = page_metadata(body)
            result.update(
                {
                    "status": response.status,
                    "final_url": response.geturl(),
                    "title": meta["title"],
                    "description": meta["description"],
                    "content_hash": digest,
                    "changed": bool(previous.get("content_hash") and previous.get("content_hash") != digest),
                }
            )
    except HTTPError as exc:
        result.update({"status": exc.code, "error": str(exc)})
    except (URLError, TimeoutError, OSError) as exc:
        result.update({"error": str(exc)})
    return result


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def entity_name(row: dict[str, str]) -> str:
    return row.get("Fond") or row.get("Angel") or row.get("Program") or row.get("Subjekt") or ""


def merge_rows(primary: list[dict[str, str]], extra: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = list(primary)
    seen = {entity_name(row).casefold() for row in rows if entity_name(row)}
    for row in extra:
        name = entity_name(row)
        if name and name.casefold() not in seen:
            rows.append(row)
            seen.add(name.casefold())
    return rows


def build_data(skip_fetch: bool) -> dict[str, Any]:
    markdown = read_report()
    tables = parse_tables(markdown)
    title, meta = extract_title_and_meta(markdown)
    sources = load_json(SOURCES_PATH, [])
    additional = load_json(ADDITIONAL_INVESTORS_PATH, {})
    previous_sources = {item.get("url"): item for item in load_json(STATUS_PATH, [])}

    if skip_fetch:
        checked_sources = [
            {
                **source,
                **previous_sources.get(source.get("url"), {}),
                "changed": previous_sources.get(source.get("url"), {}).get("changed", False),
            }
            for source in sources
        ]
    else:
        checked_sources = [None] * len(sources)
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {
                pool.submit(fetch_source, source, previous_sources.get(source["url"], {})): index
                for index, source in enumerate(sources)
            }
            for future in as_completed(futures):
                checked_sources[futures[future]] = future.result()

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_title": title,
        "report_meta": meta,
        "tldr": bullets(section_between(markdown, "## TL;DR")),
        "key_findings": parse_key_findings(markdown, tables),
        "funds": merge_rows(
            tables.get("2) Tier 1 – mezinárodně relevantní české VC fondy", []),
            additional.get("funds", []),
        ),
        "specialized_funds": merge_rows(
            tables.get("3) Tier 2 – specializované české fondy a Slovensko", []),
            additional.get("specialized_funds", []),
        ),
        "angels": merge_rows(tables.get("5) Angel investoři aktivní v 2024–26", []), additional.get("angels", [])),
        "accelerators": tables.get("9) Akcelerátory & inkubátory s investiční aktivitou", []),
        "grants": merge_rows(tables.get("C) Granty & dotace – paralelní non-dilutive runway", []), additional.get("grants", [])),
        "action_plan": parse_action_plan(markdown),
        "caveats": bullets(section_between(markdown, "## Caveats")),
        "sources": checked_sources,
    }
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true", help="Do not request remote sources.")
    args = parser.parse_args()

    data = build_data(skip_fetch=args.skip_fetch)
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.skip_fetch:
        STATUS_PATH.write_text(json.dumps(data["sources"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {OUTPUT_PATH.relative_to(ROOT)} with {len(data['sources'])} sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
