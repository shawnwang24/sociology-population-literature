from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from socdem_radar.models import Paper
from socdem_radar.state import (
    load_state,
    mark_seen,
    merge_states,
    pending_papers,
    remove_pending,
    save_state,
    sent_within,
    unseen_papers,
    update_pending,
)


class StateTests(unittest.TestCase):
    def test_mark_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = load_state(path)
            paper = Paper(title="A Paper", doi="10.1000/example")
            self.assertEqual(unseen_papers([paper], state), [paper])
            mark_seen(state, [paper], now=datetime(2026, 7, 15, tzinfo=UTC))
            save_state(path, state)
            loaded = load_state(path)
            self.assertEqual(unseen_papers([paper], loaded), [])
            json.loads(path.read_text(encoding="utf-8"))

    def test_source_id_keeps_no_doi_paper_seen_when_authors_change(self):
        now = datetime(2026, 7, 15, tzinfo=UTC)
        state = load_state("missing-state.json")
        enriched = Paper(
            title="同一篇中文文章",
            authors=["作者甲"],
            source="NCPSSD",
            source_id="stable-123",
        )
        mark_seen(state, [enriched], now=now)
        without_authors = Paper(
            title="同一篇中文文章",
            source="NCPSSD",
            source_id="stable-123",
        )
        self.assertEqual(unseen_papers([without_authors], state), [])

    def test_legacy_title_record_prevents_repeat_after_author_change(self):
        state = {
            "seen": {
                "legacy": {
                    "title": "作者信息会变化的文章",
                    "doi": "",
                    "sent_at": "2026-07-15T00:00:00Z",
                }
            }
        }
        paper = Paper(title="作者信息会变化的文章", authors=["新作者"])
        self.assertEqual(unseen_papers([paper], state), [])

    def test_recent_send_and_state_merge(self):
        now = datetime(2026, 7, 15, 12, tzinfo=UTC)
        current = {
            "last_success_at": "2026-07-15T01:00:00Z",
            "seen": {"old": {"title": "Old", "sent_at": "2026-07-15T01:00:00Z"}},
            "source_health": {},
        }
        incoming = {
            "last_success_at": "2026-07-15T10:00:00Z",
            "seen": {"new": {"title": "New", "sent_at": "2026-07-15T10:00:00Z"}},
            "source_health": {},
        }
        merged = merge_states(current, incoming)
        self.assertEqual(set(merged["seen"]), {"old", "new"})
        self.assertTrue(sent_within(merged, now, 12))
        self.assertFalse(sent_within(merged, now + timedelta(hours=13), 12))

    def test_pending_queue_is_bounded_and_sent_items_are_removed(self):
        now = datetime(2026, 7, 15, tzinfo=UTC)
        state = load_state("missing-pending-state.json")
        papers = [
            Paper(title=f"Paper {index}", doi=f"10.1000/{index}", score=float(index))
            for index in range(5)
        ]
        dropped = update_pending(state, papers, now, max_items=3, retention_days=180)
        self.assertEqual(dropped, 2)
        queued = pending_papers(state)
        self.assertEqual({paper.title for paper in queued}, {"Paper 2", "Paper 3", "Paper 4"})
        remove_pending(state, [Paper(title="Paper 4", doi="10.1000/4")])
        self.assertEqual({paper.title for paper in pending_papers(state)}, {"Paper 2", "Paper 3"})
        update_pending(
            state,
            [],
            now + timedelta(days=181),
            max_items=3,
            retention_days=180,
        )
        self.assertEqual(pending_papers(state), [])

    def test_state_merge_keeps_pending_papers_from_both_sides(self):
        now = datetime(2026, 7, 15, tzinfo=UTC)
        current = load_state("missing-current.json")
        incoming = load_state("missing-incoming.json")
        update_pending(current, [Paper(title="Current", doi="10.1000/current")], now)
        update_pending(incoming, [Paper(title="Incoming", doi="10.1000/incoming")], now)
        merged = merge_states(current, incoming)
        self.assertEqual(
            {paper.title for paper in pending_papers(merged)},
            {"Current", "Incoming"},
        )


if __name__ == "__main__":
    unittest.main()
