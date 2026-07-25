from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import ConfigError, enabled_sources, load_config
from .emailer import EmailConfigError, send_test
from .models import Paper, SourceReport
from .render import write_outputs
from .scoring import rank_papers
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="社会学与人口学文献雷达")
    parser.add_argument("--config-dir", default="config", help="配置目录，默认 config")
    parser.add_argument("--verbose", action="store_true", help="显示详细日志")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="运行完整检索流水线")
    run.add_argument("--dry-run", action="store_true", help="只生成报告，不发邮件、不更新去重状态")

    subparsers.add_parser("validate", help="检查配置")
    subparsers.add_parser("demo", help="使用合成论文离线演示评分和邮件版式")
    subparsers.add_parser("send-test", help="发送一封不访问学术 API 的 SMTP 测试邮件")
    return parser


def _demo(config, project_root: Path) -> list[str]:
    samples = [
        Paper(
            title="Occupational mismatch and spousal health: Evidence from a longitudinal household survey",
            authors=["Example Author A", "Example Author B"],
            journal="Synthetic Sociology Review",
            published_at="2026-07-15",
            abstract="This synthetic study examines skill mismatch, family spillover and self-rated health among couples in China using fixed effects models.",
            keywords=["occupational mismatch", "spousal health", "China"],
            topics=["Social Determinants of Health"],
            source="demo",
            doi="10.0000/demo.001",
            url="https://example.org/demo-001",
            metadata={"journal_priority": 2},
        ),
        Paper(
            title="Socioeconomic inequalities in healthy ageing across the life course",
            authors=["Example Author C"],
            journal="Synthetic Demography",
            published_at="2026-07-14",
            abstract="This synthetic paper studies education, wealth and health inequality in later life.",
            keywords=["health inequality", "healthy ageing"],
            source="demo",
            doi="10.0000/demo.002",
            url="https://example.org/demo-002",
            metadata={"journal_priority": 2},
        ),
        Paper(
            title="A clinical assay for a rare protein marker",
            authors=["Example Author D"],
            journal="Synthetic Clinical Journal",
            published_at="2026-07-13",
            abstract="A laboratory-only synthetic clinical paper without social inequality measures.",
            keywords=["assay", "protein"],
            source="demo",
            doi="10.0000/demo.003",
            url="https://example.org/demo-003",
        ),
    ]
    selected = rank_papers(samples, config)
    now = datetime.now(UTC)
    return write_outputs(
        project_root / "outputs" / "demo",
        selected,
        [SourceReport(name="离线合成数据", ok=True, paper_count=len(samples))],
        now,
        config,
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    try:
        config = load_config(args.config_dir)
        project_root = Path(config["_project_root"])
        if args.command == "validate":
            groups = (config.get("research_profile") or {}).get("groups") or []
            journals = [j for j in config.get("journals") or [] if j.get("enabled", True)]
            print("配置检查通过")
            print(f"- 启用主题组：{len([g for g in groups if g.get('enabled', True)])}")
            print(f"- 启用期刊：{len(journals)}")
            print(f"- 数据源：{', '.join(enabled_sources(config)) or '无'}")
            return
        if args.command == "demo":
            files = _demo(config, project_root)
            print("离线演示已生成：")
            for path in files:
                print(f"- {path}")
            return
        if args.command == "send-test":
            send_test(config, datetime.now(UTC))
            print("测试邮件已发送")
            return
        if args.command == "run":
            result = run_pipeline(config, dry_run=args.dry_run)
            print(
                json.dumps(
                    {
                        "dry_run": result.dry_run,
                        "fetched": result.fetched_count,
                        "unique": result.unique_count,
                        "selected": len(result.selected),
                        "emailed": result.emailed,
                        "outputs": result.output_files,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
    except (ConfigError, EmailConfigError, ValueError, RuntimeError) as exc:
        logging.error("%s", exc)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main(sys.argv[1:])

