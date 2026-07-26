from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


class PipelineTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
