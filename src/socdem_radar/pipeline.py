from __future__ import annotations

import logging
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from .config import enabled_sources
from .dedupe import deduplicate
from .emailer import send_digest
from .health import evaluate_source_health
from .models import Paper, RunResult, SourceReport
from .render import write_outputs
from .scoring import rank_papers, score_paper
from .sources.crossref import CrossrefClient
from .sources.magtech import fetch_magtech_current
from .sources.ncpssd import NCPSSDClient
from .sources.openalex import OpenAlexClient
from .sources.rss import fetch_feed
from .state import (
    load_state,
    mark_seen,
    pending_papers,
    remove_pending,
    save_state,
    sent_within,
    unseen_papers,
    update_pending,
)
from .summarizer import OptionalSummarizer
from .utils import utc_now


LOGGER = logging.getLogger(__name__)


def _resolve_path(project_root: Path, value: str, default: str) -> Path:
    path = Path(value or default)
    return path if path.is_absolute() else project_root / path


def _safe_fetch(
    name: str,
    callback: Callable[[], list[Paper]],
    *,
    source_type: str = "",
    journal: str = "",
    health_group: str = "",
    track_health: bool = True,
) -> tuple[list[Paper], SourceReport]:
    try:
        papers = callback()
        LOGGER.info("%s: %s papers", name, len(papers))
        return papers, SourceReport(
            name=name,
            ok=True,
            paper_count=len(papers),
            source_type=source_type,
            journal=journal,
            health_group=health_group,
            track_health=track_health,
        )
    except Exception as exc:
        LOGGER.exception("%s failed: %s", name, exc)
        return [], SourceReport(
            name=name,
            ok=False,
            error=str(exc)[:500],
            source_type=source_type,
            journal=journal,
            health_group=health_group,
            track_health=track_health,
        )


def _journal_by_feed(config: dict[str, Any]) -> list[tuple[dict[str, Any], float]]:
    feeds: list[tuple[dict[str, Any], float]] = []
    for journal in config.get("journals") or []:
        if journal.get("enabled", True) and journal.get("rss_url"):
            feeds.append(
                (
                    {
                        "name": journal.get("name", "Journal RSS"),
                        "journal": journal.get("name", ""),
                        "url": journal["rss_url"],
                    },
                    float(journal.get("priority", 0) or 0),
                )
            )
    for feed in config.get("feeds") or []:
        if feed.get("enabled", True) and feed.get("url"):
            feeds.append((feed, float(feed.get("priority", 0) or 0)))
    return feeds


def run_pipeline(config: dict[str, Any], dry_run: bool = False, now=None) -> RunResult:
    started_at = now or utc_now()
    project_root = Path(config["_project_root"])
    paths = config.get("paths") or {}
    state_path = _resolve_path(project_root, str(paths.get("state_file", "")), "data/state.json")
    output_dir = _resolve_path(project_root, str(paths.get("output_dir", "")), "outputs")
    state = load_state(state_path)

    sources_config = config.get("sources") or {}
    lookback_days = int((config.get("lookback") or {}).get("days", 14))
    start = started_at - timedelta(days=lookback_days)
    end = started_at + timedelta(days=1)
    all_papers: list[Paper] = []
    reports: list[SourceReport] = []

    if not enabled_sources(config):
        raise ValueError("没有启用任何可检索的数据源；请在 journals.yml 或 feeds.yml 中启用至少一项")

    crossref_cfg = sources_config.get("crossref") or {}
    if crossref_cfg.get("enabled", True):
        mailto = os.getenv(str(crossref_cfg.get("mailto_env", "CROSSREF_MAILTO")), "").strip()
        client = CrossrefClient(mailto=mailto, timeout=int(crossref_cfg.get("timeout_seconds", 30)))
        for journal in config.get("journals") or []:
            if not journal.get("enabled", True) or not journal.get("issns"):
                continue
            name = f"Crossref｜{journal.get('name', 'unknown journal')}"
            papers, report = _safe_fetch(
                name,
                lambda journal=journal: client.fetch_journal(
                    journal,
                    start,
                    end,
                    rows=int(crossref_cfg.get("rows_per_journal", 100)),
                    max_pages=int(crossref_cfg.get("max_pages_per_journal", 3)),
                ),
                source_type="Crossref",
                journal=str(journal.get("name", "")),
            )
            all_papers.extend(papers)
            reports.append(report)

    rss_cfg = sources_config.get("rss") or {}
    if rss_cfg.get("enabled", True):
        rss_timeout = int(rss_cfg.get("timeout_seconds", 8))
        for feed, priority in _journal_by_feed(config):
            name = f"RSS｜{feed.get('name', 'unknown feed')}"
            papers, report = _safe_fetch(
                name,
                lambda feed=feed, priority=priority: fetch_feed(
                    feed,
                    start,
                    priority,
                    timeout=rss_timeout,
                ),
                source_type="RSS",
                journal=str(feed.get("journal") or feed.get("name", "")),
            )
            all_papers.extend(papers)
            reports.append(report)

    magtech_cfg = sources_config.get("magtech") or {}
    if magtech_cfg.get("enabled", True):
        magtech_timeout = int(magtech_cfg.get("timeout_seconds", 15))
        for journal in config.get("journals") or []:
            if not journal.get("enabled", True) or not journal.get("magtech_url"):
                continue
            name = f"官网｜{journal.get('name', 'unknown journal')}"
            priority = float(journal.get("priority", 0) or 0)
            papers, report = _safe_fetch(
                name,
                lambda journal=journal, priority=priority: fetch_magtech_current(
                    journal,
                    start,
                    priority,
                    timeout=magtech_timeout,
                ),
                source_type="Magtech",
                journal=str(journal.get("name", "")),
                health_group="chinese_journal",
            )
            all_papers.extend(papers)
            reports.append(report)

    ncpssd_cfg = sources_config.get("ncpssd") or {}
    ncpssd_client: NCPSSDClient | None = None
    if ncpssd_cfg.get("enabled", True):
        ncpssd_journals = [
            journal
            for journal in config.get("journals") or []
            if journal.get("enabled", True) and journal.get("ncpssd_code")
        ]
        if ncpssd_journals:
            ncpssd_client = NCPSSDClient(
                timeout=int(ncpssd_cfg.get("timeout_seconds", 20)),
                max_workers=int(ncpssd_cfg.get("max_workers", 8)),
            )
            for journal, papers, error in ncpssd_client.fetch_journals(ncpssd_journals):
                name = f"NCPSSD·{journal.get('name', 'unknown journal')}"
                if error is not None:
                    LOGGER.warning("%s failed: %s", name, error)
                    reports.append(
                        SourceReport(
                            name=name,
                            ok=False,
                            error=str(error)[:500],
                            source_type="NCPSSD",
                            journal=str(journal.get("name", "")),
                            health_group="chinese_journal",
                        )
                    )
                    continue
                found = papers or []
                all_papers.extend(found)
                reports.append(
                    SourceReport(
                        name=name,
                        ok=True,
                        paper_count=len(found),
                        source_type="NCPSSD",
                        journal=str(journal.get("name", "")),
                        health_group="chinese_journal",
                    )
                )

    openalex_cfg = sources_config.get("openalex") or {}
    openalex_key = os.getenv(str(openalex_cfg.get("api_key_env", "OPENALEX_API_KEY")), "").strip()
    openalex_client: OpenAlexClient | None = None
    if openalex_cfg.get("enabled", True) and openalex_key:
        openalex_client = OpenAlexClient(openalex_key, timeout=int(openalex_cfg.get("timeout_seconds", 30)))
        if openalex_cfg.get("discovery_enabled", False):
            queries = (config.get("research_profile") or {}).get("discovery_queries") or []
            for query in queries:
                name = f"OpenAlex discovery｜{query}"
                papers, report = _safe_fetch(
                    name,
                    lambda query=query: openalex_client.discover(
                        str(query), start, end, per_page=int(openalex_cfg.get("discovery_results_per_query", 50))
                    ),
                    source_type="OpenAlex discovery",
                )
                all_papers.extend(papers)
                reports.append(report)
    elif openalex_cfg.get("enabled", True) and openalex_cfg.get("discovery_enabled", False):
        reports.append(
            SourceReport(
                name="OpenAlex discovery",
                ok=False,
                error="缺少 OPENALEX_API_KEY",
                source_type="OpenAlex discovery",
            )
        )

    fetched_count = len(all_papers)
    unique = deduplicate(all_papers)

    if ncpssd_client:
        full_detail_disciplines = {
            str(value) for value in ncpssd_cfg.get("full_detail_disciplines", ["人口学", "社会学"])
        }
        detail_candidates = [
            paper
            for paper in unique
            if paper.source == "NCPSSD"
            and (
                full_detail_disciplines.intersection(paper.metadata.get("disciplines") or [])
                or score_paper(paper, config).matched_terms
            )
        ]
        succeeded, failed = ncpssd_client.enrich_many(detail_candidates)
        reports.append(
            SourceReport(
                name="NCPSSD 摘要补全",
                ok=failed < len(detail_candidates) if detail_candidates else True,
                paper_count=succeeded,
                error=f"{failed} 篇详情读取失败" if failed else "",
                source_type="NCPSSD enrichment",
                track_health=False,
            )
        )

    if openalex_client and openalex_cfg.get("enrich_by_doi", True):
        enrichment_cap = int(openalex_cfg.get("max_enrichments_per_run", 40))
        candidates = sorted(
            unique,
            key=lambda paper: score_paper(paper, config).score,
            reverse=True,
        )
        attempted = 0
        failures = 0
        for paper in candidates:
            if attempted >= enrichment_cap:
                break
            if not paper.doi or (paper.abstract and paper.topics and paper.oa_url):
                continue
            attempted += 1
            try:
                openalex_client.enrich(paper)
            except Exception as exc:
                failures += 1
                LOGGER.exception("OpenAlex enrichment failed for %s: %s", paper.doi, exc)
        reports.append(
            SourceReport(
                name="OpenAlex enrichment",
                ok=failures < attempted if attempted else True,
                paper_count=max(0, attempted - failures),
                error=f"{failures} 个 DOI 补全失败" if failures else "",
                source_type="OpenAlex enrichment",
                track_health=False,
            )
        )

    health_cfg = config.get("health") or {}
    health_status = evaluate_source_health(
        state,
        reports,
        started_at,
        chinese_min_success_rate=float(health_cfg.get("chinese_min_success_rate", 0.9)),
        consecutive_failure_warning=int(health_cfg.get("consecutive_failure_warning", 2)),
    )
    primary_reports = [report for report in reports if report.track_health]
    if primary_reports and not any(report.ok for report in primary_reports):
        health_status.errors.append("所有已启用数据源均读取失败")

    queue_cfg = config.get("pending_queue") or {}
    queue_max_items = int(queue_cfg.get("max_items", 500))
    queue_retention_days = int(queue_cfg.get("retention_days", 180))
    pending_dropped = update_pending(
        state,
        [],
        started_at,
        retention_days=queue_retention_days,
        max_items=queue_max_items,
    )
    scored = [score_paper(paper, config) for paper in unique]
    combined = deduplicate([*pending_papers(state), *scored])
    not_seen = unseen_papers(combined, state)
    candidate_config = deepcopy(config)
    candidate_config["selection"] = {
        **(config.get("selection") or {}),
        "max_papers": max(queue_max_items, len(not_seen), 1),
        "max_per_journal": 0,
    }
    candidates = rank_papers(not_seen, candidate_config)
    selected = rank_papers(candidates, config)

    summarizer = OptionalSummarizer(config)
    summarizer.apply(selected)

    email_cfg = config.get("email") or {}
    should_send_empty = bool(email_cfg.get("send_empty_digest", False))
    minimum_interval_hours = float(email_cfg.get("minimum_interval_hours", 0) or 0)
    health_alert = bool(health_status.errors or health_status.warnings)
    skipped_for_interval = (
        not dry_run
        and not health_alert
        and sent_within(state, started_at, minimum_interval_hours)
    )
    if skipped_for_interval:
        health_status.warnings.append(
            f"距上次成功发送不足 {minimum_interval_hours:g} 小时，本次仅记录运行结果，不重复发信"
        )

    if not dry_run:
        pending_dropped += update_pending(
            state,
            candidates,
            started_at,
            retention_days=queue_retention_days,
            max_items=queue_max_items,
            protected=selected,
        )
        pending_count = len(state.get("pending") or {})
        will_send = (
            not skipped_for_interval
            and email_cfg.get("enabled", True)
            and bool(selected or should_send_empty)
        )
        health_status.pending_count = max(0, pending_count - len(selected)) if will_send else pending_count
        health_status.pending_dropped = pending_dropped
        save_state(state_path, state)

    output_files = write_outputs(output_dir, selected, reports, started_at, config, health_status)

    emailed = False
    if (
        not dry_run
        and not skipped_for_interval
        and email_cfg.get("enabled", True)
        and (selected or should_send_empty)
    ):
        send_digest(selected, reports, started_at, config, health_status)
        emailed = True

    if not dry_run:
        if emailed or not email_cfg.get("enabled", True):
            retention_days = int((config.get("deduplication") or {}).get("retention_days", 730))
            mark_seen(state, selected, now=started_at, retention_days=retention_days)
            remove_pending(state, selected)
            health_status.pending_count = len(state.get("pending") or {})
        save_state(state_path, state)

    return RunResult(
        started_at=started_at,
        finished_at=utc_now(),
        fetched_count=fetched_count,
        unique_count=len(unique),
        selected=selected,
        source_reports=reports,
        health_status=health_status,
        dry_run=dry_run,
        emailed=emailed,
        output_files=output_files,
    )
