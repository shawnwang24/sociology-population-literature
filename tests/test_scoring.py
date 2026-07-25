from pathlib import Path
import unittest

from socdem_radar.config import load_config
from socdem_radar.models import Paper
from socdem_radar.scoring import score_paper


ROOT = Path(__file__).resolve().parents[1]


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT / "config")

    def test_title_match_is_stronger_than_abstract_match(self):
        title_paper = Paper(title="Health inequality in later life")
        abstract_paper = Paper(title="Ageing study", abstract="We study health inequality in later life.")
        self.assertGreater(
            score_paper(title_paper, self.config).score,
            score_paper(abstract_paper, self.config).score,
        )

    def test_ascii_keyword_uses_word_boundaries(self):
        paper = Paper(title="A classification system", abstract="No social class measure is used.")
        scored = score_paper(paper, self.config)
        self.assertIn("social class", scored.matched_terms)
        title_only = Paper(title="A classification system")
        self.assertNotIn("social class", score_paper(title_only, self.config).matched_terms)

    def test_exclusion_is_hard_filter(self):
        paper = Paper(title="Health inequality in a mouse model")
        scored = score_paper(paper, self.config)
        self.assertEqual(scored.score, 0)
        self.assertIn("mouse model", scored.excluded_reason)


if __name__ == "__main__":
    unittest.main()

