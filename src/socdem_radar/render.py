from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import HealthStatus, Paper, SourceReport
from .utils import truncate


def _paper_link(paper: Paper) -> str:
    return paper.oa_url or paper.url or (f"https://doi.org/{paper.doi}" if paper.doi else "")


def render_markdown(
    papers: list[Paper],
    source_reports: list[SourceReport],
    generated_at: datetime,
    config: dict[str, Any],
    health_status: HealthStatus | None = None,
) -> str:
    profile_name = str((config.get("profile") or {}).get("name", "社会学与人口学文献雷达"))
    lines = [f"# {profile_name}", "", f"生成时间：{generated_at.isoformat()}", f"入选论文：{len(papers)} 篇", ""]
    if not papers:
        lines.extend(["本次没有达到相关性阈值且尚未推送的新论文。", ""])
    for index, paper in enumerate(papers, start=1):
        link = _paper_link(paper)
        title = f"[{paper.title}]({link})" if link else paper.title
        lines.extend(
            [
                f"## {index}. {title}",
                "",
                f"- 期刊：{paper.journal or '未知'}",
                f"- 作者：{', '.join(paper.authors) or '未知'}",
                f"- 日期：{paper.published_at or '未知'}",
                f"- 相关性得分：{paper.score:g}",
                f"- 命中主题：{'、'.join(paper.matched_groups) or '—'}",
                f"- 命中关键词：{'、'.join(paper.matched_terms) or '—'}",
                f"- DOI：{paper.doi or '—'}",
                f"- 开放获取：{'是' if paper.is_oa else ('否' if paper.is_oa is False else '未知')}",
                "",
            ]
        )
        if paper.summary_zh:
            lines.extend([f"**中文摘要：** {paper.summary_zh}", ""])
        if paper.abstract:
            max_chars = int((config.get("render") or {}).get("abstract_max_chars", 900))
            lines.extend([f"**原始摘要：** {truncate(paper.abstract, max_chars)}", ""])
        if paper.score_reasons:
            lines.extend([f"**评分依据：** {'；'.join(paper.score_reasons)}", ""])
        links = []
        if paper.doi:
            links.append(f"[DOI](https://doi.org/{paper.doi})")
        if paper.oa_url:
            links.append(f"[开放获取页面]({paper.oa_url})")
        if paper.pdf_url:
            links.append(f"[开放 PDF]({paper.pdf_url})")
        if links:
            lines.extend([" · ".join(links), ""])

    lines.extend(["---", "", "## 数据源周报", ""])
    tracked = [report for report in source_reports if report.track_health]
    if health_status:
        lines.extend(
            [
                f"- 全部来源：成功 {health_status.successful_sources}/{health_status.total_sources}，"
                f"失败 {health_status.failed_sources}",
                f"- 中文期刊：成功 {health_status.chinese_successful}/{health_status.chinese_total}，"
                f"成功率 {health_status.chinese_success_rate:.1%}",
            ]
        )
    source_types = sorted({report.source_type for report in tracked if report.source_type})
    for source_type in source_types:
        group = [report for report in tracked if report.source_type == source_type]
        lines.append(f"- {source_type}：成功 {sum(report.ok for report in group)}/{len(group)}")
    failed = [report for report in source_reports if not report.ok]
    if failed:
        lines.extend(["", "失败来源："])
        for report in failed:
            repeated = f"（连续失败 {report.consecutive_failures} 次）" if report.consecutive_failures else ""
            lines.append(f"- {report.name}{repeated}：{report.error}")
    else:
        lines.extend(["", "失败来源：无"])
    if health_status and health_status.warnings:
        lines.extend(["", "连续失败警告：", *[f"- {warning}" for warning in health_status.warnings]])
    if health_status and health_status.errors:
        lines.extend(["", "健康阈值错误：", *[f"- {error}" for error in health_status.errors]])
    lines.extend(["", "说明：系统只发送书目信息、摘要和合法链接，不下载或转发受限全文。", ""])
    return "\n".join(lines)


def render_html(
    papers: list[Paper],
    source_reports: list[SourceReport],
    generated_at: datetime,
    config: dict[str, Any],
    health_status: HealthStatus | None = None,
) -> str:
    profile_name = html.escape(str((config.get("profile") or {}).get("name", "社会学与人口学文献雷达")))
    cards: list[str] = []
    max_chars = int((config.get("render") or {}).get("abstract_max_chars", 900))
    for index, paper in enumerate(papers, start=1):
        link = html.escape(_paper_link(paper), quote=True)
        title = html.escape(paper.title)
        title_html = f'<a href="{link}" style="color:#123b66;text-decoration:none">{title}</a>' if link else title
        matched_groups = "、".join(html.escape(v) for v in paper.matched_groups) or "—"
        matched_terms = "、".join(html.escape(v) for v in paper.matched_terms) or "—"
        authors = html.escape(", ".join(paper.authors) or "未知")
        abstract = html.escape(truncate(paper.abstract, max_chars))
        summary = html.escape(paper.summary_zh)
        links = []
        if paper.doi:
            links.append(f'<a href="https://doi.org/{html.escape(paper.doi, quote=True)}">DOI</a>')
        if paper.oa_url:
            links.append(f'<a href="{html.escape(paper.oa_url, quote=True)}">开放获取页面</a>')
        if paper.pdf_url:
            links.append(f'<a href="{html.escape(paper.pdf_url, quote=True)}">开放 PDF</a>')
        summary_html = f'<p style="margin:12px 0 0"><b>中文摘要：</b>{summary}</p>' if summary else ""
        abstract_html = f'<p style="margin:12px 0 0;color:#334155"><b>原始摘要：</b>{abstract}</p>' if abstract else ""
        cards.append(
            f"""
            <section style="background:#fff;border:1px solid #dbe3ec;border-radius:10px;padding:18px;margin:0 0 16px">
              <div style="font-size:12px;color:#64748b;margin-bottom:7px">#{index} · 相关性 {paper.score:g}</div>
              <h2 style="font-size:18px;line-height:1.45;margin:0 0 9px">{title_html}</h2>
              <div style="font-size:13px;color:#475569;line-height:1.6">
                {html.escape(paper.journal or '未知期刊')} · {html.escape(paper.published_at or '日期未知')}<br>
                {authors}
              </div>
              <div style="margin-top:11px;font-size:13px"><b>命中主题：</b>{matched_groups}</div>
              <div style="margin-top:4px;font-size:13px"><b>关键词：</b>{matched_terms}</div>
              {summary_html}
              {abstract_html}
              <div style="margin-top:13px;font-size:13px">{' · '.join(links)}</div>
            </section>
            """
        )
    if not cards:
        cards.append('<section style="background:#fff;border:1px solid #dbe3ec;border-radius:10px;padding:20px">本次没有达到阈值且尚未推送的新论文。</section>')
    failed = [report for report in source_reports if not report.ok]
    tracked = [report for report in source_reports if report.track_health]
    source_rows: list[str] = []
    for source_type in sorted({report.source_type for report in tracked if report.source_type}):
        group = [report for report in tracked if report.source_type == source_type]
        source_rows.append(
            f"<li>{html.escape(source_type)}：成功 {sum(report.ok for report in group)}/{len(group)}</li>"
        )
    totals = ""
    if health_status:
        totals = (
            f"<p><b>全部来源：</b>成功 {health_status.successful_sources}/{health_status.total_sources}，"
            f"失败 {health_status.failed_sources}<br>"
            f"<b>中文期刊：</b>成功 {health_status.chinese_successful}/{health_status.chinese_total}，"
            f"成功率 {health_status.chinese_success_rate:.1%}</p>"
        )
    failure_html = "<p><b>失败来源：</b>无</p>"
    if failed:
        items = "".join(
            f"<li>{html.escape(report.name)}"
            f"{f'（连续失败 {report.consecutive_failures} 次）' if report.consecutive_failures else ''}"
            f"：{html.escape(report.error)}</li>"
            for report in failed
        )
        failure_html = f'<p style="color:#9a3412"><b>失败来源：</b></p><ul>{items}</ul>'
    alerts: list[str] = []
    if health_status:
        alerts.extend(health_status.warnings)
        alerts.extend(health_status.errors)
    alert_html = ""
    if alerts:
        alert_html = '<div style="color:#9a3412"><b>健康警告：</b><ul>' + "".join(
            f"<li>{html.escape(value)}</li>" for value in alerts
        ) + "</ul></div>"
    health_html = (
        '<section style="background:#fff;border:1px solid #dbe3ec;border-radius:10px;'
        'padding:18px;margin:18px 0"><h2 style="font-size:18px;margin-top:0">数据源周报</h2>'
        f"{totals}<ul>{''.join(source_rows)}</ul>{failure_html}{alert_html}</section>"
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#172033">
  <main style="max-width:760px;margin:0 auto;padding:28px 16px">
    <header style="padding:8px 4px 20px">
      <h1 style="font-size:25px;margin:0 0 8px">{profile_name}</h1>
      <div style="color:#64748b;font-size:13px">{html.escape(generated_at.isoformat())} · {len(papers)} 篇新论文</div>
    </header>
    {''.join(cards)}
    {health_html}
    <footer style="color:#64748b;font-size:12px;line-height:1.6;padding:12px 4px 28px">
      只提供元数据、摘要和合法链接；不下载或转发受限全文。<br>
      如结果过多或过少，请调整 topics.yml 的关键词、权重与 settings.yml 的阈值。
    </footer>
  </main>
</body></html>"""


def write_outputs(
    output_dir: str | Path,
    papers: list[Paper],
    source_reports: list[SourceReport],
    generated_at: datetime,
    config: dict[str, Any],
    health_status: HealthStatus | None = None,
) -> list[str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(papers, source_reports, generated_at, config, health_status)
    html_text = render_html(papers, source_reports, generated_at, config, health_status)
    json_text = json.dumps([paper.to_dict() for paper in papers], ensure_ascii=False, indent=2)
    files = {
        root / "latest.md": markdown,
        root / "latest.html": html_text,
        root / "latest.json": json_text + "\n",
    }
    if (config.get("render") or {}).get("archive", True):
        stamp = generated_at.strftime("%Y-%m-%dT%H%M%SZ")
        files[root / "archive" / f"{stamp}.md"] = markdown
        files[root / "archive" / f"{stamp}.json"] = json_text + "\n"
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return [str(path) for path in files]
