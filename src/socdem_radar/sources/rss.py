from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any

import feedparser
import requests

from ..models import Paper
from ..utils import clean_text, extract_doi, parse_date, unique_strings
from .http import build_session


def parse_feed_entry(entry: Any, feed: dict[str, Any], journal_priority: float = 0) -> Paper | None:
    title = clean_text(entry.get("title"))
    if not title:
        return None
    summary = clean_text(entry.get("summary") or entry.get("description"))
    link = clean_text(entry.get("link"))
    identifier = clean_text(entry.get("id"))
    doi = extract_doi(identifier, link, summary)
    authors: list[str] = []
    for author in entry.get("authors") or []:
        name = clean_text(author.get("name") if isinstance(author, dict) else author)
        if name:
            authors.append(name)
    if not authors and entry.get("author"):
        authors = [clean_text(entry.get("author"))]
    tags = [clean_text(tag.get("term")) for tag in entry.get("tags") or [] if isinstance(tag, dict)]
    published_at = parse_date(entry.get("published") or entry.get("updated"))
    return Paper(
        title=title,
        authors=unique_strings(authors),
        journal=clean_text(feed.get("journal") or feed.get("name")),
        published_at=published_at,
        discovered_at=published_at,
        doi=doi,
        url=link,
        abstract=summary,
        keywords=unique_strings(tags),
        source="RSS",
        source_id=identifier or link,
        metadata={"feed_name": feed.get("name", ""), "journal_priority": journal_priority},
    )


def _entry_datetime(entry: Any) -> datetime | None:
    structured = entry.get("published_parsed") or entry.get("updated_parsed")
    if structured:
        try:
            return datetime.fromtimestamp(calendar.timegm(structured), tz=UTC)
        except (OverflowError, ValueError, TypeError):
            return None
    parsed = parse_date(entry.get("published") or entry.get("updated"))
    if parsed:
        return datetime.fromisoformat(parsed).replace(tzinfo=UTC)
    return None


def fetch_feed(
    feed: dict[str, Any],
    start: datetime,
    journal_priority: float = 0,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> list[Paper]:
    # RSS endpoints are independent of one another. Avoid retrying a broken
    # feed repeatedly so one publisher cannot stall the entire digest.
    client = session or build_session("SocDemLiteratureRadar/0.1", retries=0)
    response = client.get(feed["url"], timeout=timeout, headers={"Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml"})
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", []):
        raise ValueError(f"RSS 解析失败：{getattr(parsed, 'bozo_exception', 'unknown error')}")
    papers: list[Paper] = []
    for entry in parsed.entries:
        entry_at = _entry_datetime(entry)
        if entry_at and entry_at < start:
            continue
        paper = parse_feed_entry(entry, feed, journal_priority=journal_priority)
        if paper:
            papers.append(paper)
    return papers
