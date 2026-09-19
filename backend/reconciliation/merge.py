from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from backend.normalization.normalizer import compare_normalized_values


def record_hash(migration_id: str, employee_id: str, payload: dict[str, Any]) -> str:
    blob = json.dumps({"migration_id": migration_id, "employee_id": employee_id, "payload": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def merge_records(existing: dict[str, Any], incoming: dict[str, Any], source_file: str) -> tuple[dict[str, Any], list[str]]:
    """Merge incoming row into canonical record; return conflicts."""
    conflicts: list[str] = []
    merged = dict(existing)
    
    # Map field names to field types for normalization
    field_type_mapping = {
        "department": "department",
        "dept": "department",
        "dept_name": "department",
        "email": "email",
        "email_address": "email",
        "mail": "email",
        "hire_date": "date",
        "joining_date": "date",
        "start_date": "date",
        "dob": "date",
        "birth_date": "date",
        "salary": "salary",
        "pay": "salary",
        "annual_salary": "salary",
    }
    
    for key, val in incoming.items():
        if not val:
            continue
        if key not in merged or not merged[key]:
            merged[key] = val
            merged.setdefault("_sources", {})[key] = source_file
        elif str(merged[key]).lower() != str(val).lower():
            # Use normalization to detect if this is a real conflict or representation difference
            field_type = field_type_mapping.get(key, "text")
            is_different, reason = compare_normalized_values(str(merged[key]), str(val), field_type)
            if is_different:
                conflicts.append(f"{key}: {merged[key]!r} vs {val!r} from {source_file}")
            else:
                # Values are the same after normalization, update source
                conflicts.append(f"{key}: representation difference normalized - {reason}")
                merged[key] = val
                existing_source = merged['_sources'].get(key, '')
                merged['_sources'][key] = f"{existing_source}, {source_file}" if existing_source else source_file
    return merged, conflicts


def dedupe_key(row: dict[str, Any]) -> str | None:
    eid = row.get("employee_id") or row.get("empId") or row.get("ID")
    if eid:
        return str(eid).strip()
    email = row.get("email") or row.get("email_address") or row.get("Email")
    if email:
        return f"email:{email.strip().lower()}"
    return None
