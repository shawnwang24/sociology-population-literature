from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    published_at: str = ""
    discovered_at: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    source: str = ""
    source_id: str = ""
    oa_url: str = ""
    pdf_url: str = ""
    is_oa: bool | None = None
    is_retracted: bool = False
    cited_by_count: int | None = None
    score: float = 0.0
    matched_groups: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    score_reasons: list[str] = field(default_factory=list)
    summary_zh: str = ""
    excluded_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Paper":
        fields = cls.__dataclass_fields__
        return cls(**{key: val for key, val in value.items() if key in fields})


@dataclass
class SourceReport:
    name: str
    ok: bool
    paper_count: int = 0
    error: str = ""
    source_type: str = ""
    journal: str = ""
    health_group: str = ""
    track_health: bool = True
    consecutive_failures: int = 0
    warning: str = ""


@dataclass
class HealthStatus:
    total_sources: int = 0
    successful_sources: int = 0
    failed_sources: int = 0
    failed_names: list[str] = field(default_factory=list)
    chinese_total: int = 0
    chinese_successful: int = 0
    chinese_success_rate: float = 1.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pending_count: int = 0
    pending_dropped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    started_at: datetime
    finished_at: datetime
    fetched_count: int
    unique_count: int
    selected: list[Paper]
    source_reports: list[SourceReport]
    health_status: HealthStatus
    dry_run: bool
    emailed: bool
    output_files: list[str] = field(default_factory=list)
