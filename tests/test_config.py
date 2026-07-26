from pathlib import Path
import unittest

from socdem_radar.config import enabled_sources, load_config


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_example_config_is_valid(self):
        config = load_config(ROOT / "config")
        self.assertEqual(config["version"], 1)
        self.assertGreaterEqual(len(config["research_profile"]["groups"]), 1)
        self.assertIn("Crossref", enabled_sources(config))

    def test_complete_core_catalog_and_research_profile_are_loaded(self):
        config = load_config(ROOT / "config")
        journals = config["journals"]
        enabled = [journal for journal in journals if journal.get("enabled", True)]
        self.assertEqual(len(journals), 152)
        self.assertEqual(len(enabled), 150)
        self.assertTrue(
            all(
                journal.get("issns")
                or journal.get("rss_url")
                or journal.get("magtech_url")
                or journal.get("ncpssd_code")
                for journal in enabled
            )
        )
        self.assertIn("Magtech", enabled_sources(config))
        self.assertIn("NCPSSD", enabled_sources(config))

        groups = {group["name"]: group for group in config["research_profile"]["groups"]}
        self.assertEqual(len(groups), 8)
        self.assertIn("occupational mismatch", groups["职业不匹配与错配"]["keywords"])
        self.assertIn("meritocratic beliefs", groups["优绩主义"]["keywords"])
        self.assertIn("subjective social status", groups["阶层认同与阶层观念"]["keywords"])
        self.assertIn("subjective well-being", groups["幸福感"]["keywords"])


if __name__ == "__main__":
    unittest.main()
