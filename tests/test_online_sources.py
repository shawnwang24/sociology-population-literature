from datetime import UTC, datetime, timedelta
import os
import unittest

from socdem_radar.sources.crossref import CrossrefClient
from socdem_radar.sources.magtech import fetch_magtech_current
from socdem_radar.sources.ncpssd import NCPSSDClient


ONLINE = os.getenv("RUN_ONLINE_TESTS", "").strip() == "1"


@unittest.skipUnless(ONLINE, "set RUN_ONLINE_TESTS=1 to run live source checks")
class OnlineSourceTests(unittest.TestCase):
    def test_crossref_social_science_and_medicine(self):
        now = datetime.now(UTC)
        papers = CrossrefClient(timeout=30).fetch_journal(
            {
                "name": "Social Science & Medicine",
                "issns": ["0277-9536", "1873-5347"],
                "priority": 1,
            },
            now - timedelta(days=365),
            now + timedelta(days=1),
            rows=5,
            max_pages=1,
        )
        self.assertTrue(papers)
        self.assertTrue(any(paper.doi for paper in papers))

    def test_ncpssd_chinese_social_sciences_with_detail(self):
        client = NCPSSDClient(timeout=30, max_workers=2)
        papers = client.fetch_journal(
            {
                "name": "中国社会科学",
                "ncpssd_code": "81908X",
                "priority": 1,
                "disciplines": ["社会学", "经济学"],
            }
        )
        self.assertTrue(papers)
        client.fetch_article_metadata(papers[0])
        self.assertTrue(papers[0].abstract)
        self.assertTrue(papers[0].authors)

    def test_magtech_population_research(self):
        papers = fetch_magtech_current(
            {
                "name": "人口研究",
                "magtech_url": "https://rkyj.ruc.edu.cn/CN/1000-6087/current.shtml",
            },
            datetime.now(UTC) - timedelta(days=365),
            timeout=30,
        )
        self.assertTrue(papers)
        self.assertTrue(papers[0].title)

    def test_ncpssd_society_fallback(self):
        papers = NCPSSDClient(timeout=30, max_workers=1).fetch_journal(
            {
                "name": "社会",
                "ncpssd_code": "97007X",
                "priority": 1,
                "disciplines": ["社会学"],
            }
        )
        self.assertTrue(papers)
        self.assertTrue(papers[0].title)


if __name__ == "__main__":
    unittest.main()
