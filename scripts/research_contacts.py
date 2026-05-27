#!/usr/bin/env python3
"""Public contact intelligence for investor outreach.

Collects only publicly exposed professional contact channels from official
websites and source pages. It does not infer private e-mail patterns or scrape
login-gated data.
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources.json"
REPORT_PATH = ROOT / "InvestReport.md"
JSON_OUT = ROOT / "data" / "contact-research.json"
CSV_OUT = ROOT / "data" / "contact-research.csv"
MD_OUT = ROOT / "CONTACT_RESEARCH.md"

EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?![\w.-])", re.I)
PHONE_RE = re.compile(
    r"(?:\+\s?(?:420|421)[\s().-]*(?:\d[\s().-]*){8,11}\d)|"
    r"(?:\b(?:420|421)[\s().-]*(?:\d[\s().-]*){8,11}\d\b)|"
    r"(?:\b\d{3}\s\d{3}\s\d{3}\b)"
)
LINK_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
SOCIAL_HOSTS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "crunchbase.com",
    "f6s.com",
    "github.com",
)
CONTACT_HINTS = (
    "contact",
    "contacts",
    "kontakt",
    "team",
    "people",
    "about",
    "apply",
    "pitch",
    "portfolio",
    "tym",
    "o-nas",
)
BLOCKED_EMAIL_PARTS = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "schema.org",
    "domain.com",
    "your@email",
    "email.com",
    "@2x.",
    "@3x.",
    "@8x",
    "cookieconsent@",
    "supertreetrunk.com",
)
BLOCKED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".css", ".js", ".ico")
BLOCKED_EXACT_EMAILS = {
    "hello@mystartup.com",
    "martin@mateju.cz",
    "marta@nextina.sk",
    "www.nation1.vcinfo@nation1.vc",
    "partnerjaroslav@nation1.vc",
    "1-hello@czechfounders.vc",
}
MANUAL_CONTACTS = {
    "J&T Ventures": {
        "emails": ["info@jtventures.cz", "media@jtventures.cz", "people@jtventures.cz"],
        "phones": ["+420 604 333 320"],
    },
    "DEPO Ventures": {
        "emails": ["team@depoventures.cz", "petr.sima@depoventures.cz"],
    },
    "Czech Founders VC": {
        "emails": ["hello@czechfounders.vc"],
        "phones": ["+420 724 244 989"],
    },
    "Purple Ventures": {
        "emails": ["ahoy@purple-ventures.com", "hello@purple-ventures.com"],
    },
    "Reflex Capital": {
        "emails": ["info@reflexcapital.com"],
        "phones": ["+420 603 194 892"],
    },
    "Rockaway Ventures": {
        "emails": ["contact@rockawayventures.com"],
    },
    "Lighthouse Ventures": {
        "emails": ["contact@lhv.vc"],
    },
    "Orbit Capital": {
        "emails": ["radovan.nesrsta@orbitcapital.com"],
    },
    "Genesis Capital": {
        "phones": ["+420 271 740 207"],
    },
    "ESPIRA Investments": {
        "phones": ["+420 222 263 815"],
    },
    "KIC KK": {
        "emails": [
            "info@kickk.cz",
            "eva.dolenska@kickk.cz",
            "kamila.krupickova@kickk.cz",
            "martina.barakova@kickk.cz",
            "petra.valdmanova@kickk.cz",
            "stepanka.kolesnyk@kickk.cz",
            "vera.koranova@kickk.cz",
            "vlastimil.vesely@kickk.cz",
        ],
        "phones": [
            "+420 725 977 530",
            "+420 608 470 775",
            "+420 608 982 920",
            "+420 734 656 979",
            "+420 736 650 376",
            "+420 775 187 808",
            "+420 775 888 404",
            "+420 777 708 748",
        ],
    },
    "StartupYard": {
        "emails": ["andrea@startupyard.com", "cedric@startupyard.com", "nikola@startupyard.com", "radim@startupyard.com"],
    },
    "CzechInvest Technology Incubation": {
        "emails": ["technologickainkubace@czechinvest.gov.cz", "tomas.bena@czechinvest.gov.cz"],
    },
}


@dataclass
class PageResult:
    url: str
    status: int | None = None
    title: str = ""
    body: str = ""
    error: str = ""


@dataclass
class ContactRecord:
    name: str
    query: str
    official_url: str
    checked_pages: list[str] = field(default_factory=list)
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    linkedin: set[str] = field(default_factory=set)
    facebook: set[str] = field(default_factory=set)
    whatsapp: set[str] = field(default_factory=set)
    other_socials: set[str] = field(default_factory=set)
    forms: set[str] = field(default_factory=set)
    people_pages: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)


def clean_text(value: str) -> str:
    value = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url: str, base: str) -> str:
    url = html.unescape(url.strip())
    if not url or url.startswith(("javascript:", "mailto:", "tel:")):
        return url
    return urljoin(base, url).split("#", 1)[0]


def normalized_phone(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .,-()")
    if "." in value or "-" in value and not value.startswith("+"):
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) < 9 or len(digits) > 16:
        return ""
    return value


def valid_email(email: str) -> bool:
    email = email.strip(".").lower()
    if email in BLOCKED_EXACT_EMAILS:
        return False
    if any(part in email for part in BLOCKED_EMAIL_PARTS):
        return False
    if email.endswith(BLOCKED_EMAIL_SUFFIXES):
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or re.search(r"\d+x(?:-|\.|$)", email):
        return False
    return True


def normalize_link(url: str) -> str:
    return url.split("?", 1)[0].rstrip("/")


def clean_record(record: ContactRecord) -> None:
    manual = MANUAL_CONTACTS.get(record.name, {})
    for email in manual.get("emails", []):
        if valid_email(email):
            record.emails.add(email.lower())
    for phone in manual.get("phones", []):
        phone = normalized_phone(phone)
        if phone:
            record.phones.add(phone)

    record.emails = {email for email in record.emails if valid_email(email)}
    record.phones = {phone for phone in record.phones if normalized_phone(phone)}

    if record.name == "Nation 1 VC":
        record.emails = {email for email in record.emails if email.endswith("@nation1.vc")}
    if record.name == "CVCA":
        record.emails = {email for email in record.emails if email.endswith("@cvca.cz")}

    record.linkedin = {url for url in record.linkedin if normalize_link(url) not in {"https://www.linkedin.com", "http://www.linkedin.com"}}
    record.forms = {url for url in record.forms if not any(part in url.lower() for part in ("wp-json", "wp-content", "data:image"))}
    record.people_pages = {url for url in record.people_pages if "wp-json" not in url.lower()}


def fetch(url: str) -> PageResult:
    headers = {
        "User-Agent": "PrautPublicContactResearch/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        with urlopen(Request(url, headers=headers), timeout=4) as response:
            raw = response.read(1_200_000)
            charset = response.headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, errors="replace")
            title = ""
            title_match = TITLE_RE.search(body)
            if title_match:
                title = clean_text(title_match.group(1))
            return PageResult(url=response.geturl(), status=response.status, title=title, body=body)
    except HTTPError as exc:
        return PageResult(url=url, status=exc.code, error=str(exc))
    except (URLError, TimeoutError, OSError) as exc:
        return PageResult(url=url, error=str(exc))


def extract_report_contacts() -> dict[str, dict[str, set[str]]]:
    text = REPORT_PATH.read_text(encoding="utf-8")
    contacts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for email in EMAIL_RE.findall(text):
      if not any(part in email.lower() for part in BLOCKED_EMAIL_PARTS):
          contacts["__all__"]["emails"].add(email)
    return contacts


def candidate_pages(base_url: str, body: str) -> list[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    urls = {base_url}

    for path in ("contact", "kontakt", "team", "apply"):
        urls.add(urljoin(origin, f"/{path}"))
        urls.add(urljoin(origin, f"/{path}/"))

    for raw in LINK_RE.findall(body):
        url = normalize_url(raw, base_url)
        if not url or url.startswith(("mailto:", "tel:", "javascript:")):
            continue
        link = urlparse(url)
        if link.netloc != parsed.netloc:
            continue
        path = link.path.lower()
        if any(hint in path for hint in CONTACT_HINTS):
            urls.add(url)

    return list(urls)[:4]


def add_social(record: ContactRecord, url: str) -> None:
    lower = url.lower()
    if "linkedin.com" in lower:
        record.linkedin.add(url)
    elif "facebook.com" in lower:
        record.facebook.add(url)
    elif "wa.me/" in lower or "whatsapp" in lower:
        record.whatsapp.add(url)
    elif any(host in lower for host in SOCIAL_HOSTS):
        record.other_socials.add(url)


def extract_contacts(record: ContactRecord, page: PageResult) -> None:
    if page.error:
        record.errors.append(f"{page.url}: {page.error}")
        return
    if page.status and page.status >= 400:
        record.errors.append(f"{page.url}: HTTP {page.status}")
        return

    record.checked_pages.append(page.url)
    record.sources.add(page.url)
    body = page.body
    visible_text = clean_text(body)

    for email in EMAIL_RE.findall(body):
        email = email.strip(".").lower()
        if valid_email(email):
            record.emails.add(email)

    for raw in re.findall(r"mailto:([^\"'?]+)", body, re.I):
        email = raw.split("?")[0].lower()
        if EMAIL_RE.fullmatch(email) and valid_email(email):
            record.emails.add(email)

    for raw in re.findall(r"tel:([^\"']+)", body, re.I):
        phone = normalized_phone(raw)
        if phone:
            record.phones.add(phone)

    for phone_match in PHONE_RE.findall(visible_text):
        phone = normalized_phone(phone_match)
        if phone and not re.fullmatch(r"\d{4}[\s.-]\d{4}[\s.-]\d{4}", phone):
            record.phones.add(phone)

    for raw in LINK_RE.findall(body):
        url = normalize_url(raw, page.url)
        lower = url.lower()
        if lower.startswith("mailto:"):
            email = lower.removeprefix("mailto:").split("?")[0]
            if EMAIL_RE.fullmatch(email) and valid_email(email):
                record.emails.add(email)
        elif lower.startswith("tel:"):
            phone = normalized_phone(lower.removeprefix("tel:"))
            if phone:
                record.phones.add(phone)
        elif lower.startswith("data:") or any(ext in lower for ext in (".png", ".jpg", ".webp", ".css", ".js")):
            continue
        elif any(host in lower for host in SOCIAL_HOSTS) or "wa.me/" in lower or "whatsapp" in lower:
            add_social(record, url)
        elif any(hint in lower for hint in ("contact", "apply", "pitch")) and "wp-json" not in lower:
            record.forms.add(url)
        elif any(hint in lower for hint in ("team", "people", "about")) and "wp-json" not in lower:
            record.people_pages.add(url)


def load_sources() -> list[dict[str, str]]:
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    seen = set()
    deduped = []
    for source in sources:
        if source["name"] in seen:
            continue
        seen.add(source["name"])
        deduped.append(source)
    return deduped


def sorted_list(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def record_to_dict(record: ContactRecord) -> dict[str, object]:
    return {
        "name": record.name,
        "query": record.query,
        "official_url": record.official_url,
        "emails": sorted_list(record.emails),
        "phones": sorted_list(record.phones),
        "linkedin": sorted_list(record.linkedin),
        "facebook": sorted_list(record.facebook),
        "whatsapp": sorted_list(record.whatsapp),
        "other_socials": sorted_list(record.other_socials),
        "forms": sorted_list(record.forms),
        "people_pages": sorted_list(record.people_pages),
        "checked_pages": sorted_list(record.checked_pages),
        "sources": sorted_list(record.sources),
        "errors": record.errors[:6],
        "notes": record.notes,
    }


def write_outputs(records: list[ContactRecord]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope_note": (
            "Only public professional contact channels from official/source pages are included. "
            "Private inferred e-mail patterns, personal phone numbers, and non-public WhatsApp data are excluded."
        ),
        "records": [record_to_dict(record) for record in records],
    }
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "official_url",
                "emails",
                "phones",
                "linkedin",
                "facebook",
                "whatsapp",
                "other_socials",
                "forms",
                "people_pages",
                "sources",
                "errors",
            ],
        )
        writer.writeheader()
        for record in payload["records"]:
            writer.writerow({key: " | ".join(record.get(key, [])) if isinstance(record.get(key), list) else record.get(key, "") for key in writer.fieldnames})

    lines = [
        "# Public contact research",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        payload["scope_note"],
        "",
    ]
    for record in payload["records"]:
        lines.extend([f"## {record['name']}", "", f"- Official/source URL: {record['official_url']}"])
        for label, key in [
            ("Emails", "emails"),
            ("Phones", "phones"),
            ("LinkedIn", "linkedin"),
            ("Facebook", "facebook"),
            ("WhatsApp", "whatsapp"),
            ("Other socials", "other_socials"),
            ("Forms", "forms"),
            ("People pages", "people_pages"),
        ]:
            values = record[key]
            if values:
                lines.append(f"- {label}: " + "; ".join(values))
        if record["errors"]:
            lines.append("- Fetch notes: " + "; ".join(record["errors"]))
        lines.append("")
    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    records = [
        ContactRecord(name=source["name"], query=source.get("query", ""), official_url=source["url"])
        for source in load_sources()
    ]

    with ThreadPoolExecutor(max_workers=12) as pool:
        home_futures = {pool.submit(fetch, record.official_url): index for index, record in enumerate(records)}
        candidate_tasks: list[tuple[int, str]] = []
        for future in as_completed(home_futures):
            index = home_futures[future]
            record = records[index]
            first_page = future.result()
            extract_contacts(record, first_page)
            for url in candidate_pages(first_page.url or record.official_url, first_page.body):
                if url not in record.checked_pages and url != first_page.url:
                    candidate_tasks.append((index, url))

        page_futures = {pool.submit(fetch, url): index for index, url in candidate_tasks}
        for future in as_completed(page_futures):
            extract_contacts(records[page_futures[future]], future.result())

    for record in records:
        clean_record(record)
        if not any([record.emails, record.phones, record.linkedin, record.facebook, record.whatsapp, record.forms]):
            record.notes.append("No public direct contact channel found on checked official pages.")

    write_outputs(records)
    print(f"Wrote {JSON_OUT.relative_to(ROOT)}, {CSV_OUT.relative_to(ROOT)} and {MD_OUT.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
