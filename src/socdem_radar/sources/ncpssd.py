from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any, Callable

import requests

from ..models import Paper
from ..utils import clean_text, extract_doi, parse_date, unique_strings
from .http import build_session


BASE_URL = "https://m.ncpssd.cn"
DETAIL_HANDLER = f"{BASE_URL}/articleinfoHandler/getjournalarticletable"
AUTHOR_AFFILIATION_RE = re.compile(r"\[\d+\]")


class _JournalPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, str]] = []
        self._heading_depth = 0
        self._heading_parts: list[str] = []
        self.current_issue = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag == "h2":
            self._heading_depth = 1
            self._heading_parts = []
        elif self._heading_depth:
            self._heading_depth += 1

        if tag != "a":
            return
        onclick = values.get("onclick", "")
        if "openDetail" not in onclick or "id=" not in onclick:
            return
        match = re.search(r"(?:[?&]|&amp;)id=([^&'\"\s]+)", onclick)
        title = clean_text(values.get("title", ""))
        if match and title:
            self.records.append(
                {
                    "source_id": clean_text(match.group(1)),
                    "title": title,
                    "issue": self.current_issue,
                }
            )

    def handle_data(self, data: str) -> None:
        if self._heading_depth and data.strip():
            self._heading_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._heading_depth:
            return
        self._heading_depth -= 1
        if tag.casefold() == "h2" or self._heading_depth == 0:
            self.current_issue = clean_text(" ".join(self._heading_parts))
            self._heading_depth = 0


def article_url(source_id: str) -> str:
    return f"{BASE_URL}/Literature/articleinfo?id={source_id}&type=journalArticle"


def parse_journal_page(
    content: str,
    journal: dict[str, Any],
    page_url: str,
    journal_priority: float = 0,
) -> list[Paper]:
    parser = _JournalPageParser()
    parser.feed(content)
    papers: list[Paper] = []
    seen: set[str] = set()
    for record in parser.records:
        source_id = record["source_id"]
        if source_id in seen:
            continue
        seen.add(source_id)
        papers.append(
            Paper(
                title=record["title"],
                journal=clean_text(journal.get("name")),
                url=article_url(source_id),
                source="NCPSSD",
                source_id=source_id,
                metadata={
                    "journal_priority": journal_priority,
                    "issue": record["issue"],
                    "source_page": page_url,
                    "ncpssd_code": clean_text(journal.get("ncpssd_code")),
                    "disciplines": journal.get("disciplines") or [],
                },
            )
        )
    return papers


def parse_article_metadata(payload: dict[str, Any], paper: Paper) -> Paper:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("NCPSSD 文献详情缺少 data 字段")

    paper.title = clean_text(data.get("titlec")) or paper.title
    paper.journal = clean_text(data.get("mediac")) or paper.journal
    paper.abstract = clean_text(data.get("remarkc"))
    paper.keywords = unique_strings(str(data.get("keywordc") or "").split(";"))
    author_text = AUTHOR_AFFILIATION_RE.sub("", str(data.get("showwriter") or ""))
    paper.authors = unique_strings(author_text.split(";"))
    paper.published_at = parse_date(data.get("publishdate") or data.get("processdate"))
    paper.discovered_at = paper.published_at
    paper.doi = extract_doi(*(str(value) for value in data.values() if value))
    paper.metadata.update(
        {
            "issn": clean_text(data.get("issn")),
            "issue": clean_text(data.get("mediasQk")) or paper.metadata.get("issue", ""),
            "pages": "-".join(
                part for part in (clean_text(data.get("beginpage")), clean_text(data.get("endpage"))) if part
            ),
            "title_en": clean_text(data.get("titlee")),
            "abstract_en": clean_text(data.get("remarke")),
            "organizations": clean_text(data.get("showorgan")),
            "ncpssd_code": clean_text(data.get("gch")) or paper.metadata.get("ncpssd_code", ""),
        }
    )
    return paper


class NCPSSDClient:
    def __init__(
        self,
        timeout: int = 20,
        max_workers: int = 8,
        session_factory: Callable[[], requests.Session] | None = None,
    ):
        self.timeout = timeout
        self.max_workers = max(1, max_workers)
        self.session_factory = session_factory or (
            lambda: build_session("SocDemLiteratureRadar/0.1", retries=1)
        )

    def fetch_journal(self, journal: dict[str, Any]) -> list[Paper]:
        page_url = f"{BASE_URL}/journal/details?gch={journal['ncpssd_code']}"
        session = self.session_factory()
        response = session.get(
            page_url,
            timeout=self.timeout,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        response.raise_for_status()
        content = response.content.decode("utf-8-sig", errors="replace")
        papers = parse_journal_page(
            content,
            journal,
            page_url,
            journal_priority=float(journal.get("priority", 0) or 0),
        )
        if not papers:
            raise ValueError("NCPSSD 期刊页未解析到当期文章")
        return papers

    def fetch_article_metadata(self, paper: Paper) -> Paper:
        session = self.session_factory()
        response = session.post(
            DETAIL_HANDLER,
            json={"lngid": paper.source_id, "type": "中文期刊文章"},
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = json.loads(response.content.decode("utf-8-sig"))
        return parse_article_metadata(payload, paper)

    def fetch_journals(
        self,
        journals: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], list[Paper] | None, Exception | None]]:
        results: list[tuple[dict[str, Any], list[Paper] | None, Exception | None]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.fetch_journal, journal): journal for journal in journals}
            for future in as_completed(futures):
                journal = futures[future]
                try:
                    results.append((journal, future.result(), None))
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    results.append((journal, None, exc))
        return results

    def enrich_many(self, papers: list[Paper]) -> tuple[int, int]:
        succeeded = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.fetch_article_metadata, paper): paper for paper in papers}
            for future in as_completed(futures):
                try:
                    future.result()
                    succeeded += 1
                except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    failed += 1
        return succeeded, failed
