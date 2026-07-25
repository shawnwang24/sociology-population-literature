from __future__ import annotations

import re
from typing import Any

from .models import Paper
from .utils import clean_text, unique_strings


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    if term and all(ord(char) < 128 for char in term) and re.search(r"[A-Za-z0-9]", term):
        return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def _matches(term: str, value: str) -> bool:
    return bool(term.strip() and value and _term_pattern(term).search(value))


def score_paper(paper: Paper, config: dict[str, Any]) -> Paper:
    profile = config.get("research_profile") or {}
    scoring = config.get("scoring") or {}
    multipliers = {
        "title": float(scoring.get("title_multiplier", 3.0)),
        "abstract": float(scoring.get("abstract_multiplier", 1.0)),
        "keywords": float(scoring.get("keyword_multiplier", 2.0)),
        "topics": float(scoring.get("topic_multiplier", 1.5)),
    }
    fields = {
        "title": clean_text(paper.title),
        "abstract": clean_text(paper.abstract),
        "keywords": " | ".join(paper.keywords),
        "topics": " | ".join(paper.topics),
    }

    exclude_terms = unique_strings(profile.get("exclude_keywords") or [])
    combined = "\n".join(fields.values())
    for term in exclude_terms:
        if _matches(term, combined):
            paper.excluded_reason = f"命中排除词：{term}"
            paper.score = 0.0
            return paper

    total = 0.0
    matched_groups: list[str] = []
    matched_terms: list[str] = []
    reasons: list[str] = []
    max_terms = int(scoring.get("max_terms_per_group", 3))

    for group in profile.get("groups") or []:
        if not group.get("enabled", True):
            continue
        group_name = str(group.get("name", "未命名主题"))
        group_weight = float(group.get("weight", 1.0))
        term_scores: list[tuple[float, str, str]] = []
        for raw_term in unique_strings(group.get("keywords") or []):
            matching_fields = [name for name, value in fields.items() if _matches(raw_term, value)]
            if not matching_fields:
                continue
            best_field = max(matching_fields, key=lambda name: multipliers[name])
            term_scores.append((group_weight * multipliers[best_field], raw_term, best_field))

        if term_scores:
            term_scores.sort(reverse=True)
            chosen = term_scores[:max_terms]
            group_score = sum(item[0] for item in chosen)
            total += group_score
            matched_groups.append(group_name)
            matched_terms.extend(item[1] for item in chosen)
            details = "、".join(f"{term}（{field}）" for _, term, field in chosen)
            reasons.append(f"{group_name} +{group_score:g}：{details}")

    journal_priority = float(paper.metadata.get("journal_priority", 0) or 0)
    if journal_priority:
        priority_weight = float(scoring.get("journal_priority_weight", 1.0))
        addition = journal_priority * priority_weight
        total += addition
        reasons.append(f"期刊优先级 +{addition:g}")

    watched_authors = unique_strings(profile.get("watched_authors") or [])
    author_text = " | ".join(paper.authors)
    author_matches = [name for name in watched_authors if _matches(name, author_text)]
    if author_matches:
        addition = float(scoring.get("watched_author_bonus", 5.0))
        total += addition
        reasons.append(f"关注作者 +{addition:g}：{'、'.join(author_matches)}")

    paper.score = round(total, 2)
    paper.matched_groups = unique_strings(matched_groups)
    paper.matched_terms = unique_strings(matched_terms)
    paper.score_reasons = reasons
    return paper


def rank_papers(papers: list[Paper], config: dict[str, Any]) -> list[Paper]:
    selection = config.get("selection") or {}
    min_score = float(selection.get("min_score", 1.0))
    scored = [score_paper(paper, config) for paper in papers]
    eligible = [paper for paper in scored if not paper.excluded_reason and paper.score >= min_score and not paper.is_retracted]
    eligible.sort(key=lambda paper: (paper.score, paper.published_at, paper.title.casefold()), reverse=True)

    max_per_journal = int(selection.get("max_per_journal", 0) or 0)
    max_papers = int(selection.get("max_papers", 15))
    if max_per_journal <= 0:
        return eligible[:max_papers]

    result: list[Paper] = []
    counts: dict[str, int] = {}
    for paper in eligible:
        journal_key = paper.journal.casefold() or "(unknown)"
        if counts.get(journal_key, 0) >= max_per_journal:
            continue
        result.append(paper)
        counts[journal_key] = counts.get(journal_key, 0) + 1
        if len(result) >= max_papers:
            break
    return result
