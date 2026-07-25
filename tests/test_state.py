from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from socdem_radar.models import Paper
from socdem_radar.state import load_state, mark_seen, save_state, unseen_papers


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


if __name__ == "__main__":
    unittest.main()
