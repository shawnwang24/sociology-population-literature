from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import requests

from ..models import Paper
from ..utils import clean_text, crossref_date, normalize_doi, unique_strings
from .http import build_session


API_ROOT = "https://api.crossref.org"


def _author_name(author: dict[str, Any]) -> str:
    given = clean_text(author.get("given"))
    family = clean_text(author.get("family"))
    name = " ".join(part for part in (given, family) if part)
    return name or clean_text(author.get("name"))


def parse_crossref_item(item: dict[str, Any], journal: dict[str, Any]) -> Paper | None:
    title_values = item.get("title") or []
    title = clean_text(title_values[0] if title_values else "")
    if not title:
        return None
    doi = normalize_doi(item.get("DOI"))
    container = item.get("container-title") or []
    journal_name = clean_text(container[0] if container else journal.get("name", ""))
    created = crossref_date(item, "created", "deposited", "indexed")
    published = crossref_date(item, "published-online", "published-print", "published", "issued", "created")
    url = clean_text(item.get("URL")) or (f"https://doi.org/{doi}" if doi else "")
    links = item.get("link") or []
    pdf_url = ""
    for link in links:
        content_type = str(link.get("content-type", "")).casefold()
        if "pdf" in content_type:
            pdf_url = clean_text(link.get("URL"))
            break
    return Paper(
        title=title,
        authors=unique_strings(_author_name(author) for author in item.get("author") or []),
        journal=journal_name,
        published_at=published,
        discovered_at=created,
        doi=doi,
        url=url,
        abstract=clean_text(item.get("abstract")),
        keywords=unique_strings([*(item.get("subject") or []), *(item.get("subtype") or [])]),
        source="Crossref",
        source_id=doi or clean_text(item.get("URL")),
        pdf_url=pdf_url,
        metadata={
            "journal_priority": journal.get("priority", 0),
            "issn": item.get("ISSN") or journal.get("issns") or [],
            "crossref_type": item.get("type", ""),
        },
    )


class CrossrefClient:
    def __init__(self, mailto: str = "", timeout: int = 30, session: requests.Session | None = None):
        contact = f"; mailto:{mailto}" if mailto else ""
        self.session = session or build_session(f"SocDemLiteratureRadar/0.1 ({contact})")
        self.mailto = mailto
        self.timeout = timeout

    def fetch_journal(
        self,
        journal: dict[str, Any],
        start: datetime,
        end: datetime,
        rows: int = 100,
        max_pages: int = 5,
    ) -> list[Paper]:
        papers: list[Paper] = []
        for issn in journal.get("issns") or []:
            cursor = "*"
            for _ in range(max_pages):
                endpoint = f"{API_ROOT}/journals/{quote(str(issn), safe='')}/works"
                params = {
                    "filter": ",".join(
                        [
                            f"from-created-date:{start.date().isoformat()}",
                            f"until-created-date:{end.date().isoformat()}",
                            "type:journal-article",
                        ]
                    ),
                    "rows": min(max(rows, 1), 1000),
                    "cursor": cursor,
                }
                if self.mailto:
                    params["mailto"] = self.mailto
                response = self.session.get(endpoint, params=params, timeout=self.timeout)
                # Crossref does not expose a /journals/{issn} route for every
                # valid print/electronic ISSN. One missing alias should not
                # discard results already fetched through another ISSN.
                if response.status_code == 404:
                    break
                response.raise_for_status()
                message = response.json().get("message") or {}
                items = message.get("items") or []
                for item in items:
                    paper = parse_crossref_item(item, journal)
                    if paper:
                        papers.append(paper)
                next_cursor = message.get("next-cursor")
                if not next_cursor or next_cursor == cursor or len(items) < rows:
                    break
                cursor = next_cursor
        return papers
