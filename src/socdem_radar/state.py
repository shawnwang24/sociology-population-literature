from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Paper
from .utils import iso_z, paper_key, utc_now


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {"version": 1, "last_success_at": None, "seen": {}}
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取状态文件 {state_path}: {exc}") from exc
    state.setdefault("version", 1)
    state.setdefault("last_success_at", None)
    state.setdefault("seen", {})
    return state


def unseen_papers(papers: list[Paper], state: dict[str, Any]) -> list[Paper]:
    seen = state.get("seen") or {}
    return [paper for paper in papers if paper_key(paper.doi, paper.title, paper.authors) not in seen]


def mark_seen(state: dict[str, Any], papers: list[Paper], now: datetime | None = None, retention_days: int = 730) -> None:
    now = now or utc_now()
    seen = state.setdefault("seen", {})
    for paper in papers:
        key = paper_key(paper.doi, paper.title, paper.authors)
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


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, state_path)
