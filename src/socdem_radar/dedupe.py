from __future__ import annotations

from .models import Paper
from .utils import first_nonempty, paper_key, unique_strings


def merge_papers(left: Paper, right: Paper) -> Paper:
    """Merge two records for the same paper, preserving the richest metadata."""
    left.title = max((left.title, right.title), key=len)
    left.authors = unique_strings([*left.authors, *right.authors])
    left.journal = first_nonempty(left.journal, right.journal)
    left.published_at = first_nonempty(left.published_at, right.published_at)
    left.discovered_at = first_nonempty(left.discovered_at, right.discovered_at)
    left.doi = first_nonempty(left.doi, right.doi)
    left.url = first_nonempty(left.url, right.url)
    left.abstract = max((left.abstract, right.abstract), key=len)
    left.keywords = unique_strings([*left.keywords, *right.keywords])
    left.topics = unique_strings([*left.topics, *right.topics])
    left.oa_url = first_nonempty(left.oa_url, right.oa_url)
    left.pdf_url = first_nonempty(left.pdf_url, right.pdf_url)
    left.is_oa = left.is_oa if left.is_oa is not None else right.is_oa
    left.is_retracted = left.is_retracted or right.is_retracted
    left.cited_by_count = max(v for v in (left.cited_by_count, right.cited_by_count) if v is not None) if any(
        v is not None for v in (left.cited_by_count, right.cited_by_count)
    ) else None
    sources = unique_strings(
        [part.strip() for value in (left.source, right.source) for part in value.split(",") if part.strip()]
    )
    left.source = ", ".join(sources)
    left.metadata.update(right.metadata)
    return left


def deduplicate(papers: list[Paper]) -> list[Paper]:
    by_key: dict[str, Paper] = {}
    title_aliases: dict[str, str] = {}
    for paper in papers:
        exact_key = paper_key(paper.doi, paper.title, paper.authors)
        title_key = paper_key("", paper.title, paper.authors)
        known_key = title_aliases.get(title_key, exact_key)
        if known_key in by_key:
            by_key[known_key] = merge_papers(by_key[known_key], paper)
        elif exact_key in by_key:
            by_key[exact_key] = merge_papers(by_key[exact_key], paper)
            known_key = exact_key
        else:
            by_key[exact_key] = paper
            known_key = exact_key
        title_aliases[title_key] = known_key
    return list(by_key.values())
