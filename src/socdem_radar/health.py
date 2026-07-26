from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import HealthStatus, SourceReport
from .utils import iso_z


def evaluate_source_health(
    state: dict[str, Any],
    reports: list[SourceReport],
    now: datetime,
    *,
    chinese_min_success_rate: float = 0.9,
    consecutive_failure_warning: int = 2,
) -> HealthStatus:
    tracked = [report for report in reports if report.track_health]
    records = state.setdefault("source_health", {})
    active_names = {report.name for report in tracked}
    for stale_name in set(records) - active_names:
        del records[stale_name]

    warnings: list[str] = []
    for report in tracked:
        previous = records.get(report.name) or {}
        if report.ok:
            consecutive = 0
            record = {
                "consecutive_failures": 0,
                "last_success_at": iso_z(now),
                "last_failure_at": previous.get("last_failure_at"),
                "last_error": "",
            }
        else:
            consecutive = int(previous.get("consecutive_failures", 0) or 0) + 1
            record = {
                "consecutive_failures": consecutive,
                "last_success_at": previous.get("last_success_at"),
                "last_failure_at": iso_z(now),
                "last_error": report.error,
            }
        records[report.name] = record
        report.consecutive_failures = consecutive
        if not report.ok and consecutive >= consecutive_failure_warning:
            report.warning = f"已连续失败 {consecutive} 次"
            warnings.append(f"{report.name} 已连续失败 {consecutive} 次：{report.error}")

    failed = [report for report in tracked if not report.ok]
    chinese = [report for report in tracked if report.health_group == "chinese_journal"]
    chinese_successful = sum(report.ok for report in chinese)
    chinese_rate = chinese_successful / len(chinese) if chinese else 1.0
    errors: list[str] = []
    if chinese and chinese_rate < chinese_min_success_rate:
        errors.append(
            "中文期刊来源成功率 "
            f"{chinese_successful}/{len(chinese)}（{chinese_rate:.1%}）"
            f"低于阈值 {chinese_min_success_rate:.1%}"
        )

    return HealthStatus(
        total_sources=len(tracked),
        successful_sources=sum(report.ok for report in tracked),
        failed_sources=len(failed),
        failed_names=[report.name for report in failed],
        chinese_total=len(chinese),
        chinese_successful=chinese_successful,
        chinese_success_rate=chinese_rate,
        warnings=warnings,
        errors=errors,
    )
