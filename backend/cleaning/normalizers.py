from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from dateutil import parser as date_parser

from backend.models.schemas import TransformationRecord


def normalize_whitespace(value: str) -> tuple[str, Optional[TransformationRecord]]:
    cleaned = value.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned == value:
        return value, None
    return cleaned, TransformationRecord(
        record_id="",
        field="",
        source_value=value,
        transformed_value=cleaned,
        transformation_type="WHITESPACE_NORMALIZATION",
        reason="Trimmed leading/trailing whitespace and collapsed spaces",
        confidence=0.99,
        timestamp=datetime.utcnow(),
    )


def normalize_email(value: str) -> tuple[str, Optional[TransformationRecord]]:
    v = value.strip().lower()
    if v == value:
        return value, None
    return v, TransformationRecord(
        record_id="",
        field="email",
        source_value=value,
        transformed_value=v,
        transformation_type="EMAIL_CASE_NORMALIZATION",
        reason="Normalized email to lowercase",
        confidence=0.98,
        timestamp=datetime.utcnow(),
    )


def normalize_date(value: str) -> tuple[Optional[str], Optional[TransformationRecord], Optional[str]]:
    """Return ISO date string, transformation, or error reason if ambiguous."""
    raw = value.strip()
    if not raw:
        return None, None, "Empty date"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw, None, None

    # US-style m/d/Y vs d/m/Y ambiguity for 01/02/1995
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", raw):
        parts = raw.split("/")
        m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
        if m <= 12 and d <= 12 and m != d:
            return None, None, f"Ambiguous date {raw} (could be MDY or DMY)"

    try:
        dt = date_parser.parse(raw, dayfirst=False)
        iso = dt.date().isoformat()
        if iso == raw:
            return iso, None, None
        return iso, TransformationRecord(
            record_id="",
            field="",
            source_value=raw,
            transformed_value=iso,
            transformation_type="DATE_NORMALIZATION",
            reason="Parsed date into ISO format YYYY-MM-DD",
            confidence=0.92,
            timestamp=datetime.utcnow(),
        ), None
    except (ValueError, OverflowError):
        return None, None, f"Could not parse date: {raw}"


def split_full_name(value: str) -> tuple[Optional[str], Optional[str], Optional[TransformationRecord]]:
    parts = value.strip().split()
    if len(parts) < 2:
        return parts[0] if parts else None, "", None
    first, last = parts[0], " ".join(parts[1:])
    return first, last, TransformationRecord(
        record_id="",
        field="full_name",
        source_value=value,
        transformed_value=f"{first} {last}",
        transformation_type="NAME_SPLIT",
        reason="Split full name into first and last for target schema",
        confidence=0.9,
        timestamp=datetime.utcnow(),
    )
