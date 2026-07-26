from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"缺少配置文件：{path}")
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"配置文件顶层必须是对象：{path}")
    return value


def load_config(config_dir: str | Path) -> dict[str, Any]:
    root = Path(config_dir).expanduser().resolve()
    settings = _read_yaml(root / "settings.yml")
    topics = _read_yaml(root / "topics.yml")
    journals = _read_yaml(root / "journals.yml")
    feeds = _read_yaml(root / "feeds.yml")

    config = {
        **settings,
        "research_profile": topics.get("research_profile", {}),
        "journals": journals.get("journals", []),
        "feeds": feeds.get("feeds", []),
        "_config_dir": str(root),
        "_project_root": str(root.parent),
    }
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    errors: list[str] = []
    if config.get("version") != 1:
        errors.append("settings.yml 中 version 必须为 1")

    selection = config.get("selection") or {}
    if float(selection.get("min_score", 0)) < 0:
        errors.append("selection.min_score 不能为负数")
    if int(selection.get("max_papers", 0)) < 1:
        errors.append("selection.max_papers 必须至少为 1")

    email = config.get("email") or {}
    if float(email.get("minimum_interval_hours", 0)) < 0:
        errors.append("email.minimum_interval_hours 不能为负数")
    if int(email.get("retry_attempts", 3)) < 1:
        errors.append("email.retry_attempts 必须至少为 1")

    pending_queue = config.get("pending_queue") or {}
    if int(pending_queue.get("retention_days", 180)) < 1:
        errors.append("pending_queue.retention_days 必须至少为 1")
    if int(pending_queue.get("max_items", 500)) < 1:
        errors.append("pending_queue.max_items 必须至少为 1")

    health = config.get("health") or {}
    chinese_min_success_rate = float(health.get("chinese_min_success_rate", 0.9))
    if not 0 <= chinese_min_success_rate <= 1:
        errors.append("health.chinese_min_success_rate 必须在 0 到 1 之间")
    if int(health.get("consecutive_failure_warning", 2)) < 1:
        errors.append("health.consecutive_failure_warning 必须至少为 1")

    groups = (config.get("research_profile") or {}).get("groups") or []
    if not groups:
        errors.append("topics.yml 至少需要一个 research_profile.groups 主题组")
    for index, group in enumerate(groups, start=1):
        if not group.get("name"):
            errors.append(f"第 {index} 个主题组缺少 name")
        if not group.get("keywords"):
            errors.append(f"主题组 {group.get('name', index)} 缺少 keywords")

    for index, journal in enumerate(config.get("journals") or [], start=1):
        if not journal.get("name"):
            errors.append(f"第 {index} 本期刊缺少 name")
        if (
            journal.get("enabled", True)
            and not journal.get("issns")
            and not journal.get("rss_url")
            and not journal.get("magtech_url")
            and not journal.get("ncpssd_code")
        ):
            errors.append(
                f"启用的期刊 {journal.get('name', index)} 至少需要 "
                "issns、rss_url、magtech_url 或 ncpssd_code"
            )

    if errors:
        raise ConfigError("配置检查未通过：\n- " + "\n- ".join(errors))


def env_value(config: dict[str, Any], key: str, default: str = "") -> str:
    env_name = str(config.get(key) or "").strip()
    if not env_name:
        return default
    return os.getenv(env_name, default).strip()


def enabled_sources(config: dict[str, Any]) -> list[str]:
    names: list[str] = []
    crossref_enabled = (config.get("sources") or {}).get("crossref", {}).get("enabled", True)
    if crossref_enabled and any(j.get("enabled", True) and j.get("issns") for j in config.get("journals", [])):
        names.append("Crossref")
    rss_enabled = (config.get("sources") or {}).get("rss", {}).get("enabled", True)
    has_rss = any(j.get("enabled", True) and j.get("rss_url") for j in config.get("journals", [])) or any(
        f.get("enabled", True) and f.get("url") for f in config.get("feeds", [])
    )
    if rss_enabled and has_rss:
        names.append("RSS")
    magtech_enabled = (config.get("sources") or {}).get("magtech", {}).get("enabled", True)
    if magtech_enabled and any(
        j.get("enabled", True) and j.get("magtech_url") for j in config.get("journals", [])
    ):
        names.append("Magtech")
    ncpssd_enabled = (config.get("sources") or {}).get("ncpssd", {}).get("enabled", True)
    if ncpssd_enabled and any(
        j.get("enabled", True) and j.get("ncpssd_code") for j in config.get("journals", [])
    ):
        names.append("NCPSSD")
    openalex = (config.get("sources") or {}).get("openalex", {})
    if openalex.get("enabled", True) and openalex.get("discovery_enabled", False):
        names.append("OpenAlex discovery")
    return names
