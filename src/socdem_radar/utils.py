from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Iterable


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    doi = value.strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.rstrip(".,; ").lower()


def extract_doi(*values: str) -> str:
    for value in values:
        if not value:
            continue
        match = DOI_RE.search(value)
        if match:
            return normalize_doi(match.group(0))
    return ""


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^\w\u3400-\u9fff]+", " ", value, flags=re.UNICODE)
    return SPACE_RE.sub(" ", value).strip()


def paper_key(
    doi: str,
    title: str,
    authors: Iterable[str] = (),
    *,
    source_id: str = "",
    source: str = "",
) -> str:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    normalized_source_id = clean_text(source_id).casefold()
    if normalized_source_id:
        source_name = clean_text(source).split(",", 1)[0].casefold()
        digest = hashlib.sha256(f"{source_name}|{normalized_source_id}".encode("utf-8")).hexdigest()[:24]
        return f"source:{digest}"
    identity = normalize_title(title)
    first_author = normalize_title(next(iter(authors), ""))
    digest = hashlib.sha256(f"{identity}|{first_author}".encode("utf-8")).hexdigest()[:24]
    return f"title:{digest}"


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def parse_date(value: Any) -> str:
    """Return YYYY-MM-DD when a source date can be understood."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)) and value:
        try:
            parts = list(value) + [1, 1]
            return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
        except (TypeError, ValueError, IndexError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    match = re.search(r"(19|20)\d{2}(?:[-/]\d{1,2})?(?:[-/]\d{1,2})?", text)
    if match:
        parts = re.split(r"[-/]", match.group(0))
        try:
            return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1).isoformat()
        except ValueError:
            return ""
    return ""


def crossref_date(message: dict[str, Any], *keys: str) -> str:
    for key in keys:
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts:
            parsed = parse_date(parts[0])
            if parsed:
                return parsed
    return ""


def truncate(value: str, limit: int) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def unique_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = clean_text(raw)
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result
