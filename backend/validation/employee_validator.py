from __future__ import annotations

from typing import Any, Optional

import yaml
from pydantic import ValidationError

from backend.config import settings
from backend.models.schemas import EmployeeRecord, TargetSchemaField


def load_target_schema() -> dict[str, TargetSchemaField]:
    path = settings.data_dir / "target-schema" / "employees.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {name: TargetSchemaField(**meta) for name, meta in raw["fields"].items()}


def validate_employee_payload(data: dict[str, Any]) -> tuple[Optional[EmployeeRecord], Optional[str]]:
    """
    Validate employee payload against target schema.
    
    Returns:
        (validated_record, error_message)
    """
    target_schema = load_target_schema()
    
    # Check for missing required fields first
    missing_fields = []
    for field_name, field_meta in target_schema.items():
        if field_meta.required and (field_name not in data or not data.get(field_name)):
            missing_fields.append(field_name)
    
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    try:
        return EmployeeRecord.model_validate(data), None
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            msg = err.get('msg', '')
            msgs.append(f"{loc}: {msg}")
        
        return None, "; ".join(msgs)
