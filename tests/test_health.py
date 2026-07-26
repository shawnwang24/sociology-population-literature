from datetime import UTC, datetime, timedelta
import unittest

from socdem_radar.health import evaluate_source_health
from socdem_radar.models import SourceReport
from socdem_radar.render import render_markdown


class SourceHealthTests(unittest.TestCase):
    def test_consecutive_failures_warn_and_success_resets_counter(self):
        state = {}
        now = datetime(2026, 7, 26, tzinfo=UTC)
        first = [SourceReport(name="NCPSSD·测试期刊", ok=False, error="timeout")]
        status = evaluate_source_health(state, first, now, consecutive_failure_warning=2)
        self.assertEqual(status.warnings, [])
        self.assertEqual(first[0].consecutive_failures, 1)

        second = [SourceReport(name="NCPSSD·测试期刊", ok=False, error="timeout")]
        status = evaluate_source_health(
            state,
            second,
            now + timedelta(days=7),
            consecutive_failure_warning=2,
        )
        self.assertEqual(second[0].consecutive_failures, 2)
        self.assertIn("连续失败 2 次", status.warnings[0])

        recovered = [SourceReport(name="NCPSSD·测试期刊", ok=True)]
        status = evaluate_source_health(state, recovered, now + timedelta(days=14))
        self.assertEqual(status.warnings, [])
        self.assertEqual(recovered[0].consecutive_failures, 0)

    def test_chinese_success_rate_below_threshold_is_error(self):
        reports = [
            SourceReport(
                name=f"NCPSSD·期刊{index}",
                ok=index < 8,
                error="" if index < 8 else "failed",
                health_group="chinese_journal",
            )
            for index in range(10)
        ]
        status = evaluate_source_health(
            {},
            reports,
            datetime(2026, 7, 26, tzinfo=UTC),
            chinese_min_success_rate=0.9,
        )
        self.assertEqual(status.chinese_success_rate, 0.8)
        self.assertEqual(len(status.errors), 1)

    def test_weekly_report_lists_counts_and_failed_names(self):
        reports = [
            SourceReport(name="Crossref｜A", ok=True, source_type="Crossref"),
            SourceReport(name="NCPSSD·B", ok=False, error="timeout", source_type="NCPSSD"),
        ]
        status = evaluate_source_health({}, reports, datetime(2026, 7, 26, tzinfo=UTC))
        output = render_markdown([], reports, datetime(2026, 7, 26, tzinfo=UTC), {}, status)
        self.assertIn("全部来源：成功 1/2，失败 1", output)
        self.assertIn("NCPSSD·B", output)


if __name__ == "__main__":
    unittest.main()
