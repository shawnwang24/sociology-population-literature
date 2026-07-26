from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Paper
from .utils import iso_z, normalize_title, paper_key, utc_now


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {"version": 1, "last_success_at": None, "seen": {}, "source_health": {}, "pending": {}}
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取状态文件 {state_path}: {exc}") from exc
    state.setdefault("version", 1)
    state.setdefault("last_success_at", None)
    state.setdefault("seen", {})
    state.setdefault("source_health", {})
    state.setdefault("pending", {})
    return state


def unseen_papers(papers: list[Paper], state: dict[str, Any]) -> list[Paper]:
    seen = state.get("seen") or {}
    seen_titles = {
        normalize_title(str(record.get("title", "")))
        for record in seen.values()
        if isinstance(record, dict) and record.get("title")
    }
    return [
        paper
        for paper in papers
        if paper_key(
            paper.doi,
            paper.title,
            paper.authors,
            source_id=paper.source_id,
            source=paper.source,
        )
        not in seen
        and normalize_title(paper.title) not in seen_titles
    ]


def mark_seen(state: dict[str, Any], papers: list[Paper], now: datetime | None = None, retention_days: int = 730) -> None:
    now = now or utc_now()
    seen = state.setdefault("seen", {})
    for paper in papers:
        key = paper_key(
            paper.doi,
            paper.title,
            paper.authors,
            source_id=paper.source_id,
            source=paper.source,
        )
        seen[key] = {
            "title": paper.title,
            "doi": paper.doi,
            "sent_at": iso_z(now),
        }
    cutoff = now.astimezone(UTC) - timedelta(days=retention_days)
    for key, record in list(seen.items()):
        try:
            sent_at = datetime.fromisoformat(str(record.get("sent_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if sent_at < cutoff:
            del seen[key]
    state["last_success_at"] = iso_z(now)


def sent_within(state: dict[str, Any], now: datetime, hours: float) -> bool:
    if hours <= 0:
        return False
    value = str(state.get("last_success_at") or "").strip()
    if not value:
        return False
    try:
        previous = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=UTC)
    return now.astimezone(UTC) - previous.astimezone(UTC) < timedelta(hours=hours)


def pending_papers(state: dict[str, Any]) -> list[Paper]:
    papers: list[Paper] = []
    for record in (state.get("pending") or {}).values():
        if not isinstance(record, dict) or not isinstance(record.get("paper"), dict):
            continue
        try:
            paper = Paper.from_dict(record["paper"])
        except (TypeError, ValueError):
            continue
        if paper.title:
            papers.append(paper)
    return papers


def update_pending(
    state: dict[str, Any],
    papers: list[Paper],
    now: datetime,
    *,
    retention_days: int = 180,
    max_items: int = 500,
    protected: list[Paper] | None = None,
) -> int:
    pending = state.setdefault("pending", {})
    cutoff = now.astimezone(UTC) - timedelta(days=retention_days)
    dropped = 0
    for key, record in list(pending.items()):
        if not isinstance(record, dict) or _timestamp(record.get("queued_at")) < cutoff:
            del pending[key]
            dropped += 1

    for paper in papers:
        key = paper_key(
            paper.doi,
            paper.title,
            paper.authors,
            source_id=paper.source_id,
            source=paper.source,
        )
        previous = pending.get(key) or {}
        pending[key] = {
            "paper": paper.to_dict(),
            "queued_at": previous.get("queued_at") or iso_z(now),
            "last_seen_at": iso_z(now),
        }

    protected_titles = {normalize_title(paper.title) for paper in (protected or [])}
    ordered = sorted(
        pending.items(),
        key=lambda item: (
            normalize_title(str((item[1].get("paper") or {}).get("title", ""))) in protected_titles,
            float((item[1].get("paper") or {}).get("score", 0) or 0),
            -_timestamp(item[1].get("queued_at")).timestamp(),
        ),
        reverse=True,
    )
    limit = max(1, max_items)
    kept = dict(ordered[:limit])
    dropped += max(0, len(ordered) - len(kept))
    state["pending"] = kept
    return dropped


def remove_pending(state: dict[str, Any], papers: list[Paper]) -> None:
    pending = state.setdefault("pending", {})
    sent_titles = {normalize_title(paper.title) for paper in papers}
    sent_keys = {
        paper_key(
            paper.doi,
            paper.title,
            paper.authors,
            source_id=paper.source_id,
            source=paper.source,
        )
        for paper in papers
    }
    for key, record in list(pending.items()):
        paper_data = record.get("paper") if isinstance(record, dict) else {}
        title = normalize_title(str((paper_data or {}).get("title", "")))
        if key in sent_keys or title in sent_titles:
            del pending[key]


def _timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def merge_states(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(current)
    merged.setdefault("version", 1)
    merged_seen = merged.setdefault("seen", {})
    for key, record in (incoming.get("seen") or {}).items():
        previous = merged_seen.get(key) or {}
        if _timestamp(record.get("sent_at")) >= _timestamp(previous.get("sent_at")):
            merged_seen[key] = deepcopy(record)

    merged_health = merged.setdefault("source_health", {})
    for name, record in (incoming.get("source_health") or {}).items():
        previous = merged_health.get(name) or {}
        incoming_time = max(
            _timestamp(record.get("last_success_at")),
            _timestamp(record.get("last_failure_at")),
        )
        previous_time = max(
            _timestamp(previous.get("last_success_at")),
            _timestamp(previous.get("last_failure_at")),
        )
        if incoming_time >= previous_time:
            merged_health[name] = deepcopy(record)

    merged_pending = merged.setdefault("pending", {})
    for key, record in (incoming.get("pending") or {}).items():
        previous = merged_pending.get(key) or {}
        if _timestamp(record.get("last_seen_at")) >= _timestamp(previous.get("last_seen_at")):
            merged_pending[key] = deepcopy(record)

    latest_success = max(
        _timestamp(current.get("last_success_at")),
        _timestamp(incoming.get("last_success_at")),
    )
    merged["last_success_at"] = iso_z(latest_success) if latest_success.year > 1 else None
    seen_titles = {
        normalize_title(str(record.get("title", "")))
        for record in merged_seen.values()
        if isinstance(record, dict) and record.get("title")
    }
    for key, record in list(merged_pending.items()):
        paper_data = record.get("paper") if isinstance(record, dict) else {}
        paper = Paper.from_dict(paper_data) if isinstance(paper_data, dict) else Paper(title="")
        paper_identity = paper_key(
            paper.doi,
            paper.title,
            paper.authors,
            source_id=paper.source_id,
            source=paper.source,
        )
        if paper_identity in merged_seen or normalize_title(paper.title) in seen_titles:
            del merged_pending[key]
    return merged


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, state_path)
