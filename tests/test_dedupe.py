import unittest

from socdem_radar.dedupe import deduplicate
from socdem_radar.models import Paper


class DedupeTests(unittest.TestCase):
    def test_same_doi_merges_richer_metadata(self):
        papers = [
            Paper(title="Health Inequality", doi="https://doi.org/10.1000/ABC", abstract="short", source="Crossref"),
            Paper(
                title="Health inequality",
                doi="10.1000/abc",
                abstract="a substantially richer abstract",
                topics=["Population Health"],
                source="OpenAlex",
            ),
        ]
        result = deduplicate(papers)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].abstract, "a substantially richer abstract")
        self.assertIn("Population Health", result[0].topics)
        self.assertIn("Crossref", result[0].source)
        self.assertIn("OpenAlex", result[0].source)

    def test_title_fallback_merges_missing_doi(self):
        papers = [
            Paper(title="Social Mobility and Health", authors=["A. Scholar"]),
            Paper(title="Social mobility & health", authors=["A. Scholar"], abstract="abstract"),
        ]
        result = deduplicate(papers)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].abstract, "abstract")


if __name__ == "__main__":
    unittest.main()

