from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from ..models import Paper
from ..utils import clean_text, extract_doi, parse_date, unique_strings
from .http import build_session


ARTICLE_ID_RE = re.compile(r"^art\d+$", re.IGNORECASE)
ISSUE_DATE_RE = re.compile(r"刊出日期\s*[:：]?\s*((?:19|20)\d{2}[-年/]\d{1,2}[-月/]\d{1,2})")
AUTHOR_SEPARATOR_RE = re.compile(r"[,，;；、\s]+")


def _upgrade_same_host_url(base_url: str, value: str) -> str:
    joined = urljoin(base_url, value)
    base = urlsplit(base_url)
    target = urlsplit(joined)
    if base.scheme == "https" and target.scheme == "http" and base.netloc.casefold() == target.netloc.casefold():
        target = target._replace(scheme="https")
        return urlunsplit(target)
    return joined


class _MagtechCurrentParser(HTMLParser):
    """Parse both current and legacy Magtech current-issue templates."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.records: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.container_tag = ""
        self.container_depth = 0
        self.stack: list[tuple[str, set[str], str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = {value.casefold() for value in values.get("class", "").split() if value}

        if self.current is None:
            article_id = values.get("id", "")
            if ARTICLE_ID_RE.match(article_id) and "noselectrow" in classes:
                self.current = {
                    "source_id": article_id,
                    "title": [],
                    "authors": [],
                    "citation": [],
                    "abstract": [],
                    "all_text": [],
                    "hrefs": [],
                    "url": "",
                }
                self.container_tag = tag
                self.container_depth = 1
                self.stack = [(tag, classes, None)]
            return

        if tag == self.container_tag:
            self.container_depth += 1

        field: str | None = None
        if tag == "a" and (
            "biaoti" in classes or any("j-title-1" in ancestor_classes for _, ancestor_classes, _ in self.stack)
        ):
            field = "title"
            href = values.get("href", "")
            if href:
                self.current["url"] = _upgrade_same_host_url(self.page_url, href)
        elif "zuozhe" in classes or "j-author" in classes:
            field = "authors"
        elif "kmnjq" in classes or "j-volumn" in classes:
            field = "citation"
        elif "j-abstract" in classes or (tag == "div" and {"white_content", "zhaiyao"}.issubset(classes)):
            field = "abstract"

        href = values.get("href", "")
        if href:
            self.current["hrefs"].append(_upgrade_same_host_url(self.page_url, href))
        self.stack.append((tag, classes, field))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.current is None or not data.strip():
            return
        self.current["all_text"].append(data)
        for _, _, field in reversed(self.stack):
            if field:
                self.current[field].append(data)
                break

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        tag = tag.casefold()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag == self.container_tag:
            self.container_depth -= 1
            if self.container_depth <= 0:
                self.records.append(self.current)
                self.current = None
                self.container_tag = ""
                self.container_depth = 0
                self.stack = []


def parse_magtech_current(
    content: str,
    journal: dict[str, Any],
    page_url: str,
    journal_priority: float = 0,
) -> list[Paper]:
    parser = _MagtechCurrentParser(page_url)
    parser.feed(content)
    page_text = clean_text(content)
    date_match = ISSUE_DATE_RE.search(page_text)
    issue_date = parse_date(date_match.group(1).replace("年", "-").replace("月", "-").replace("日", "")) if date_match else ""

    papers: list[Paper] = []
    for record in parser.records:
        title = clean_text(" ".join(record["title"]))
        if not title:
            continue
        author_text = clean_text(" ".join(record["authors"]))
        authors = unique_strings(part for part in AUTHOR_SEPARATOR_RE.split(author_text) if part)
        citation = clean_text(" ".join(record["citation"]))
        abstract = clean_text(" ".join(record["abstract"]))
        url = clean_text(record["url"])
        doi = extract_doi(" ".join(record["all_text"]), *record["hrefs"])
        published_at = issue_date or parse_date(citation)
        papers.append(
            Paper(
                title=title,
                authors=authors,
                journal=clean_text(journal.get("name")),
                published_at=published_at,
                discovered_at=published_at,
                doi=doi,
                url=url,
                abstract=abstract,
                source="Magtech",
                source_id=clean_text(record["source_id"]) or url,
                metadata={
                    "journal_priority": journal_priority,
                    "citation": citation,
                    "source_page": page_url,
                },
            )
        )
    return papers


def fetch_magtech_current(
    journal: dict[str, Any],
    start: datetime,
    journal_priority: float = 0,
    timeout: int = 15,
    session: requests.Session | None = None,
) -> list[Paper]:
    del start  # The page contains one current issue; persistent state prevents repeat mail.
    client = session or build_session("SocDemLiteratureRadar/0.1", retries=1)
    page_url = str(journal["magtech_url"])
    response = client.get(
        page_url,
        timeout=timeout,
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    papers = parse_magtech_current(
        response.text,
        journal,
        page_url,
        journal_priority=journal_priority,
    )
    if not papers:
        raise ValueError("期刊官网当期目录中未解析到文章")
    return papers
