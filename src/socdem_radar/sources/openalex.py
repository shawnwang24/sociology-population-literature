from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import requests

from ..dedupe import merge_papers
from ..models import Paper
from ..utils import clean_text, normalize_doi, unique_strings
from .http import build_session


API_ROOT = "https://api.openalex.org"


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions or []:
            positioned.append((int(position), word))
    positioned.sort(key=lambda item: item[0])
    return clean_text(" ".join(word for _, word in positioned))


def _location_url(location: dict[str, Any] | None, key: str) -> str:
    return clean_text((location or {}).get(key))


def parse_openalex_work(work: dict[str, Any], source_name: str = "OpenAlex") -> Paper | None:
    title = clean_text(work.get("display_name") or work.get("title"))
    if not title:
        return None
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = clean_text(author.get("display_name"))
        if name:
            authors.append(name)
    primary_location = work.get("primary_location") or {}
    best_oa = work.get("best_oa_location") or {}
    source = primary_location.get("source") or {}
    doi = normalize_doi((work.get("ids") or {}).get("doi") or work.get("doi"))
    topics = [clean_text(topic.get("display_name")) for topic in work.get("topics") or []]
    keywords = [clean_text(keyword.get("display_name")) for keyword in work.get("keywords") or []]
    oa_status = work.get("open_access") or {}
    url = _location_url(primary_location, "landing_page_url") or (f"https://doi.org/{doi}" if doi else clean_text(work.get("id")))
    oa_url = _location_url(best_oa, "landing_page_url")
    pdf_url = _location_url(best_oa, "pdf_url")
    return Paper(
        title=title,
        authors=unique_strings(authors),
        journal=clean_text(source.get("display_name")),
        published_at=clean_text(work.get("publication_date")),
        discovered_at=clean_text(work.get("created_date")),
        doi=doi,
        url=url,
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        keywords=unique_strings(keywords),
        topics=unique_strings(topics),
        source=source_name,
        source_id=clean_text(work.get("id")),
        oa_url=oa_url,
        pdf_url=pdf_url,
        is_oa=bool(oa_status.get("is_oa")) if oa_status else None,
        is_retracted=bool(work.get("is_retracted")),
        cited_by_count=work.get("cited_by_count"),
        metadata={
            "openalex_id": clean_text(work.get("id")),
            "openalex_type": clean_text(work.get("type")),
        },
    )


class OpenAlexClient:
    def __init__(self, api_key: str, timeout: int = 30, session: requests.Session | None = None):
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or build_session("SocDemLiteratureRadar/0.1")

    def _params(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(values or {})
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def get_by_doi(self, doi: str) -> Paper | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        external_id = quote(f"https://doi.org/{normalized}", safe="")
        response = self.session.get(
            f"{API_ROOT}/works/{external_id}", params=self._params(), timeout=self.timeout
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_openalex_work(response.json())

    def enrich(self, paper: Paper) -> Paper:
        if not paper.doi:
            return paper
        enriched = self.get_by_doi(paper.doi)
        if enriched:
            return merge_papers(paper, enriched)
        return paper

    def discover(self, query: str, start: datetime, end: datetime, per_page: int = 50) -> list[Paper]:
        filters = ",".join(
            [
                f"from_publication_date:{start.date().isoformat()}",
                f"to_publication_date:{end.date().isoformat()}",
                "type:article|review",
            ]
        )
        params = self._params(
            {
                "search": query,
                "filter": filters,
                "sort": "publication_date:desc",
                "per-page": min(max(per_page, 1), 200),
            }
        )
        response = self.session.get(f"{API_ROOT}/works", params=params, timeout=self.timeout)
        response.raise_for_status()
        papers = []
        for work in response.json().get("results") or []:
            paper = parse_openalex_work(work, source_name="OpenAlex discovery")
            if paper:
                paper.metadata["discovery_query"] = query
                papers.append(paper)
        return papers

