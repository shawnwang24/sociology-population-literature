from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from socdem_radar.config import load_config
from socdem_radar.models import Paper
from socdem_radar.pipeline import run_pipeline


ROOT = Path(__file__).resolve().parents[1]


class FakeCrossrefClient:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_journal(self, journal, start, end, rows=100, max_pages=3):
        return [
            Paper(
                title="Health inequality and social class in China",
                authors=["A. Scholar"],
                journal=journal["name"],
                published_at="2026-07-15",
                doi="10.1000/pipeline-test",
                abstract="A study of health inequality, social class and China.",
                source="Crossref",
                metadata={"journal_priority": journal.get("priority", 0)},
            )
        ]


class EmptyCrossrefClient:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_journal(self, journal, start, end, rows=100, max_pages=3):
        return []


class FailingCrossrefClient:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_journal(self, journal, start, end, rows=100, max_pages=3):
        raise requests.Timeout("simulated timeout")


class BacklogCrossrefClient:
    papers: list[Paper] = []

    def __init__(self, *args, **kwargs):
        pass

    def fetch_journal(self, journal, start, end, rows=100, max_pages=3):
        return [deepcopy(paper) for paper in self.papers]


class PipelineTests(unittest.TestCase):
    def test_all_sources_failed_sends_warning_report_and_returns_health_error(self):
        base = load_config(ROOT / "config")
        with tempfile.TemporaryDirectory() as directory:
            config = deepcopy(base)
            config["_project_root"] = directory
            config["paths"] = {"state_file": "data/state.json", "output_dir": "outputs"}
            config["journals"] = [
                {
                    "name": "Failing Journal",
                    "enabled": True,
                    "language": "en",
                    "issns": ["1234-5678"],
                }
            ]
            config["sources"]["openalex"]["enabled"] = False
            config["sources"]["rss"]["enabled"] = False
            config["sources"]["magtech"]["enabled"] = False
            config["sources"]["ncpssd"]["enabled"] = False
            with (
                patch("socdem_radar.pipeline.CrossrefClient", FailingCrossrefClient),
                patch("socdem_radar.pipeline.send_digest") as mocked_send,
            ):
                result = run_pipeline(
                    config,
                    dry_run=False,
                    now=datetime(2026, 7, 15, 12, tzinfo=UTC),
                )
            self.assertIn("所有已启用数据源均读取失败", result.health_status.errors)
            self.assertTrue(result.emailed)
            mocked_send.assert_called_once()

    def test_empty_successful_run_sends_heartbeat_email(self):
        base = load_config(ROOT / "config")
        with tempfile.TemporaryDirectory() as directory:
            config = deepcopy(base)
            config["_project_root"] = directory
            config["paths"] = {"state_file": "data/state.json", "output_dir": "outputs"}
            config["journals"] = [
                {
                    "name": "Heartbeat Journal",
                    "enabled": True,
                    "language": "en",
                    "issns": ["1234-5678"],
                }
            ]
            config["sources"]["openalex"]["enabled"] = False
            config["sources"]["rss"]["enabled"] = False
            config["sources"]["magtech"]["enabled"] = False
            config["sources"]["ncpssd"]["enabled"] = False
            now = datetime(2026, 7, 15, 12, tzinfo=UTC)
            with (
                patch("socdem_radar.pipeline.CrossrefClient", EmptyCrossrefClient),
                patch("socdem_radar.pipeline.send_digest") as mocked_send,
            ):
                result = run_pipeline(config, dry_run=False, now=now)
            self.assertEqual(result.selected, [])
            self.assertTrue(result.emailed)
            mocked_send.assert_called_once()

    def test_successful_run_persists_state_and_prevents_repeat(self):
        base = load_config(ROOT / "config")
        with tempfile.TemporaryDirectory() as directory:
            config = deepcopy(base)
            config["_project_root"] = directory
            config["paths"] = {"state_file": "data/state.json", "output_dir": "outputs"}
            config["email"]["enabled"] = False
            config["sources"]["openalex"]["enabled"] = False
            config["sources"]["rss"]["enabled"] = False
            config["sources"]["magtech"]["enabled"] = False
            config["sources"]["ncpssd"]["enabled"] = False
            now = datetime(2026, 7, 15, 12, tzinfo=UTC)
            with patch("socdem_radar.pipeline.CrossrefClient", FakeCrossrefClient):
                first = run_pipeline(config, dry_run=False, now=now)
                second = run_pipeline(config, dry_run=False, now=now)
            self.assertEqual(len(first.selected), 1)
            self.assertEqual(len(second.selected), 0)
            self.assertTrue((Path(directory) / "data" / "state.json").exists())
            self.assertTrue((Path(directory) / "outputs" / "latest.html").exists())

    def test_recent_success_skips_email_without_consuming_new_papers(self):
        base = load_config(ROOT / "config")
        with tempfile.TemporaryDirectory() as directory:
            config = deepcopy(base)
            config["_project_root"] = directory
            config["paths"] = {"state_file": "data/state.json", "output_dir": "outputs"}
            config["sources"]["openalex"]["enabled"] = False
            config["sources"]["rss"]["enabled"] = False
            config["sources"]["magtech"]["enabled"] = False
            config["sources"]["ncpssd"]["enabled"] = False
            state_path = Path(directory) / "data" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                '{"version":1,"last_success_at":"2026-07-15T08:00:00Z","seen":{},"source_health":{}}',
                encoding="utf-8",
            )
            now = datetime(2026, 7, 15, 12, tzinfo=UTC)
            with (
                patch("socdem_radar.pipeline.CrossrefClient", FakeCrossrefClient),
                patch("socdem_radar.pipeline.send_digest") as mocked_send,
            ):
                result = run_pipeline(config, dry_run=False, now=now)
            self.assertEqual(len(result.selected), 1)
            self.assertFalse(result.emailed)
            mocked_send.assert_not_called()
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["seen"], {})
            self.assertEqual(persisted["last_success_at"], "2026-07-15T08:00:00Z")
            self.assertEqual(len(persisted["pending"]), 1)

    def test_unsent_backlog_is_delivered_after_it_leaves_source_window(self):
        base = load_config(ROOT / "config")
        with tempfile.TemporaryDirectory() as directory:
            config = deepcopy(base)
            config["_project_root"] = directory
            config["paths"] = {"state_file": "data/state.json", "output_dir": "outputs"}
            config["selection"]["max_papers"] = 2
            config["selection"]["max_per_journal"] = 0
            config["email"]["minimum_interval_hours"] = 0
            config["pending_queue"] = {"retention_days": 180, "max_items": 10}
            config["journals"] = [
                {
                    "name": "Backlog Journal",
                    "enabled": True,
                    "language": "en",
                    "issns": ["1234-5678"],
                }
            ]
            config["sources"]["openalex"]["enabled"] = False
            config["sources"]["rss"]["enabled"] = False
            config["sources"]["magtech"]["enabled"] = False
            config["sources"]["ncpssd"]["enabled"] = False
            BacklogCrossrefClient.papers = [
                Paper(
                    title=f"Health inequality and social class study {index}",
                    doi=f"10.1000/backlog-{index}",
                    journal="Backlog Journal",
                    published_at="2026-07-15",
                    abstract="Health inequality, occupational class and wellbeing in China.",
                    source="Crossref",
                    metadata={"journal_priority": 1},
                )
                for index in range(3)
            ]
            with (
                patch("socdem_radar.pipeline.CrossrefClient", BacklogCrossrefClient),
                patch("socdem_radar.pipeline.send_digest"),
            ):
                first = run_pipeline(
                    config,
                    dry_run=False,
                    now=datetime(2026, 7, 15, 12, tzinfo=UTC),
                )
                BacklogCrossrefClient.papers = []
                second = run_pipeline(
                    config,
                    dry_run=False,
                    now=datetime(2026, 8, 15, 12, tzinfo=UTC),
                )
            self.assertEqual(len(first.selected), 2)
            self.assertEqual(len(second.selected), 1)
            state = json.loads(
                (Path(directory) / "data" / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["pending"], {})


if __name__ == "__main__":
    unittest.main()
