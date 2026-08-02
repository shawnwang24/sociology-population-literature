import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from socdem_radar.models import Paper
from socdem_radar.sources.crossref import CrossrefClient, parse_crossref_item
from socdem_radar.sources.magtech import fetch_magtech_current, parse_magtech_current
from socdem_radar.sources.ncpssd import parse_article_metadata, parse_journal_page
from socdem_radar.sources.openalex import OpenAlexClient, parse_openalex_work, reconstruct_abstract
from socdem_radar.sources.rss import fetch_feed


class FakeResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self.payload = payload or {}
        self.content = content
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class SourceParsingTests(unittest.TestCase):
    def test_parse_ncpssd_journal_page(self):
        html = """
        <div class="catalog">
          <h2>2026年 第3期</h2>
          <a onclick="openDetail('/Literature/articleinfo?id=LDJJYJ2026003004&amp;type=journalArticle')"
             title="劳动力流动、配置效率红利与县域经济增长">文章</a>
        </div>
        """
        papers = parse_journal_page(
            html,
            {"name": "劳动经济研究", "ncpssd_code": "60089X"},
            "https://m.ncpssd.cn/journal/details?gch=60089X",
            journal_priority=2,
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source_id, "LDJJYJ2026003004")
        self.assertEqual(papers[0].metadata["issue"], "2026年 第3期")
        self.assertEqual(papers[0].metadata["journal_priority"], 2)

    def test_parse_ncpssd_article_metadata(self):
        paper = parse_journal_page(
            """
            <h2>2026年 第3期</h2>
            <a onclick="openDetail('/Literature/articleinfo?id=LDJJYJ2026003004&amp;type=journalArticle')"
               title="目录标题">文章</a>
            """,
            {"name": "劳动经济研究", "ncpssd_code": "60089X"},
            "https://m.ncpssd.cn/journal/details?gch=60089X",
        )[0]
        parse_article_metadata(
            {
                "data": {
                    "titlec": "劳动力流动、配置效率红利与县域经济增长",
                    "mediac": "劳动经济研究",
                    "keywordc": "劳动力流动;县域经济增长",
                    "remarkc": "这是一段中文摘要。",
                    "showwriter": "句国艳[1];匡国静[2]",
                    "publishdate": "2026-06-15",
                    "issn": "2095-6703",
                    "beginpage": "55",
                    "endpage": "89",
                    "gch": "60089X",
                }
            },
            paper,
        )
        self.assertEqual(paper.authors, ["句国艳", "匡国静"])
        self.assertEqual(paper.abstract, "这是一段中文摘要。")
        self.assertEqual(paper.keywords, ["劳动力流动", "县域经济增长"])
        self.assertEqual(paper.published_at, "2026-06-15")
        self.assertEqual(paper.metadata["pages"], "55-89")

    def test_reconstruct_openalex_abstract(self):
        index = {"Health": [0], "inequality": [1], "matters": [2]}
        self.assertEqual(reconstruct_abstract(index), "Health inequality matters")

    def test_parse_crossref_item(self):
        item = {
            "title": ["A paper"],
            "DOI": "10.1000/ABC",
            "author": [{"given": "Ada", "family": "Scholar"}],
            "container-title": ["A Journal"],
            "published-online": {"date-parts": [[2026, 7, 15]]},
            "created": {"date-parts": [[2026, 7, 14]]},
            "abstract": "<jats:p>An abstract.</jats:p>",
            "subject": ["Sociology"],
            "URL": "https://doi.org/10.1000/ABC",
        }
        paper = parse_crossref_item(item, {"name": "Fallback", "priority": 3})
        self.assertIsNotNone(paper)
        self.assertEqual(paper.doi, "10.1000/abc")
        self.assertEqual(paper.published_at, "2026-07-15")
        self.assertEqual(paper.abstract, "An abstract.")
        self.assertEqual(paper.metadata["journal_priority"], 3)

    def test_parse_openalex_work(self):
        work = {
            "id": "https://openalex.org/W1",
            "display_name": "A work",
            "publication_date": "2026-07-15",
            "ids": {"doi": "https://doi.org/10.1000/ABC"},
            "abstract_inverted_index": {"An": [0], "abstract": [1]},
            "authorships": [{"author": {"display_name": "Ada Scholar"}}],
            "topics": [{"display_name": "Population Health"}],
            "keywords": [{"display_name": "health inequality"}],
            "primary_location": {
                "landing_page_url": "https://publisher.example/paper",
                "source": {"display_name": "A Journal"},
            },
            "best_oa_location": {"landing_page_url": "https://repository.example/paper", "pdf_url": "https://repository.example/paper.pdf"},
            "open_access": {"is_oa": True},
            "is_retracted": False,
            "cited_by_count": 2,
        }
        paper = parse_openalex_work(work)
        self.assertIsNotNone(paper)
        self.assertEqual(paper.abstract, "An abstract")
        self.assertTrue(paper.is_oa)
        self.assertEqual(paper.pdf_url, "https://repository.example/paper.pdf")

    def test_crossref_client_builds_incremental_query(self):
        session = FakeSession([FakeResponse({"message": {"items": [], "next-cursor": "next"}})])
        client = CrossrefClient(mailto="me@example.com", session=session)
        papers = client.fetch_journal(
            {"name": "A Journal", "issns": ["1234-5678"]},
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 15, tzinfo=UTC),
            rows=25,
        )
        self.assertEqual(papers, [])
        _, kwargs = session.calls[0]
        self.assertIn("from-created-date:2026-07-01", kwargs["params"]["filter"])
        self.assertEqual(kwargs["params"]["mailto"], "me@example.com")
        self.assertNotIn("cursor-max", kwargs["params"])

    def test_crossref_skips_unknown_issn_alias(self):
        session = FakeSession(
            [
                FakeResponse(status_code=404),
                FakeResponse({"message": {"items": [], "next-cursor": "next"}}),
            ]
        )
        client = CrossrefClient(session=session)
        papers = client.fetch_journal(
            {"name": "A Journal", "issns": ["0000-0000", "1234-5678"]},
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 15, tzinfo=UTC),
        )
        self.assertEqual(papers, [])
        self.assertEqual(len(session.calls), 2)
        self.assertIn("1234-5678", session.calls[1][0])

    def test_openalex_doi_lookup_uses_one_encoded_identifier(self):
        session = FakeSession([FakeResponse({}, status_code=404)])
        client = OpenAlexClient("key", session=session)
        self.assertIsNone(client.get_by_doi("10.1000/ABC"))
        url, kwargs = session.calls[0]
        self.assertIn("https%3A%2F%2Fdoi.org%2F10.1000%2Fabc", url)
        self.assertEqual(kwargs["params"]["api_key"], "key")

    def test_rss_fetch_uses_timeout_and_parses_item(self):
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <rss version='2.0'><channel><title>Feed</title><item>
        <title>Health inequality paper</title>
        <link>https://doi.org/10.1000/rss</link>
        <description>An abstract</description>
        <pubDate>Wed, 15 Jul 2026 10:00:00 GMT</pubDate>
        </item></channel></rss>"""
        session = FakeSession([FakeResponse(content=xml)])
        papers = fetch_feed(
            {"name": "Feed", "url": "https://example.org/feed.xml"},
            datetime(2026, 7, 1, tzinfo=UTC),
            session=session,
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "10.1000/rss")
        self.assertEqual(session.calls[0][1]["timeout"], 30)

    def test_parse_magtech_legacy_current_issue(self):
        html = """
        <div class="njq">2026年 第50卷 第3期 刊出日期：2026-05-29</div>
        <DIV id='art3948' class=noselectrow>
          <a href="/CN/Y2026/V50/I3/3" class="biaoti">分化与趋同：中国老年人老化态度的演进</a>
          <dd class="zuozhe">梁宏, 陈云龙</dd>
          <dd class="kmnjq">2026, 50(3): 3-18.</dd>
          <div id="Abstract3948" class="white_content zhaiyao">这是一段中文摘要。</div>
        </DIV>
        """
        papers = parse_magtech_current(
            html,
            {"name": "人口研究"},
            "https://rkyj.ruc.edu.cn/CN/1000-6087/current.shtml",
            journal_priority=2,
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].authors, ["梁宏", "陈云龙"])
        self.assertEqual(papers[0].published_at, "2026-05-29")
        self.assertEqual(papers[0].abstract, "这是一段中文摘要。")
        self.assertEqual(papers[0].url, "https://rkyj.ruc.edu.cn/CN/Y2026/V50/I3/3")
        self.assertEqual(papers[0].metadata["journal_priority"], 2)

    def test_parse_magtech_modern_current_issue(self):
        html = """
        <div>刊出日期：2026-05-20</div>
        <li id="art718" class="noselectrow">
          <div class="j-title-1"><a href="http://src.ruc.edu.cn/CN/Y2026/V14/I3/5">职业与健康研究</a></div>
          <div class="j-author">王修晓 袁章伶</div>
          <span class="j-volumn">社会学评论. 2026, 14(3): 5-25.</span>
          <div class="j-abstract">完整摘要。</div>
        </li>
        """
        papers = parse_magtech_current(
            html,
            {"name": "社会学评论"},
            "https://src.ruc.edu.cn/CN/2095-5154/current.shtml",
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].authors, ["王修晓", "袁章伶"])
        self.assertEqual(papers[0].url, "https://src.ruc.edu.cn/CN/Y2026/V14/I3/5")
        self.assertEqual(papers[0].source, "Magtech")

    @patch("socdem_radar.sources.ncpssd.NCPSSDClient.fetch_journal")
    def test_magtech_uses_ncpssd_fallback_after_official_site_failure(self, fallback_fetch):
        fallback_fetch.return_value = [
            Paper(title="A recovered paper", journal="社会", source="NCPSSD", source_id="paper-1")
        ]
        session = FakeSession([FakeResponse(status_code=503)])

        papers = fetch_magtech_current(
            {
                "name": "社会",
                "magtech_url": "https://journal.example/current.shtml",
                "ncpssd_fallback_code": "97007X",
            },
            datetime(2026, 7, 1, tzinfo=UTC),
            session=session,
        )

        self.assertEqual([paper.title for paper in papers], ["A recovered paper"])
        self.assertEqual(fallback_fetch.call_args.args[0]["ncpssd_code"], "97007X")


if __name__ == "__main__":
    unittest.main()
