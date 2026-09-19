from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator
import re


class MigrationStatus(str, Enum):
    CREATED = "CREATED"
    UPLOAD = "UPLOAD"
    INSPECT_FILES = "INSPECT_FILES"
    PROFILE_SCHEMAS = "PROFILE_SCHEMAS"
    INFER_MAPPINGS = "INFER_MAPPINGS"
    APPLY_MAPPINGS = "APPLY_MAPPINGS"
    CLEAN_DATA = "CLEAN_DATA"
    VALIDATE = "VALIDATE"
    RECONCILE = "RECONCILE"
    WAITING_HUMAN = "WAITING_HUMAN"
    PUSH_TARGET = "PUSH_TARGET"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class EscalationType(str, Enum):
    AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    UNCLEANABLE_VALUE = "UNCLEANABLE_VALUE"
    CONFLICTING_RECORDS = "CONFLICTING_RECORDS"
    TARGET_PUSH_FAILURE = "TARGET_PUSH_FAILURE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    TRANSFORMATION_REQUIRED = "TRANSFORMATION_REQUIRED"
    SCHEMA_ERROR = "SCHEMA_ERROR"


class HumanDecision(str, Enum):
    APPROVE = "APPROVE"
    CORRECT = "CORRECT"
    REJECT = "REJECT"


class TargetRecordStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    ROLLED_BACK = "ROLLED_BACK"


class EmployeeRecord(BaseModel):
    employee_id: str
    first_name: str
    last_name: str
    full_name: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    date_of_birth: date
    department: Optional[str] = None
    job_title: Optional[str] = None
    hire_date: Optional[date] = None

    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, v: str) -> str:
        if not re.match(r"^EMP-[A-Z0-9]+$", v):
            raise ValueError("employee_id must match EMP-XXXX pattern")
        return v

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def strip_names(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class TargetSchemaField(BaseModel):
    type: str
    required: bool = False
    format: Optional[str] = None
    pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    description: Optional[str] = None


class FieldMappingCandidate(BaseModel):
    target_field: str
    confidence: float
    reasons: list[str] = Field(default_factory=list)


class FieldMappingDecision(BaseModel):
    source_column: str
    source_file: str
    target_field: Optional[str] = None
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    candidates: list[FieldMappingCandidate] = Field(default_factory=list)
    auto_applied: bool = False
    escalated: bool = False


class TransformationRecord(BaseModel):
    record_id: str
    field: str
    source_value: Any
    transformed_value: Any
    transformation_type: str
    reason: str
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    migration_id: str
    record_id: Optional[str] = None
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    actor: str = "agent"
    decision: Optional[str] = None


class ActivityEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    migration_id: str
    message: str
    level: str = "info"


class EscalationPayload(BaseModel):
    id: Optional[int] = None
    migration_id: str
    escalation_type: EscalationType
    status: EscalationStatus = EscalationStatus.OPEN
    record_id: Optional[str] = None
    field: Optional[str] = None
    source_value: Optional[str] = None
    source_values: dict[str, Any] = Field(default_factory=dict)
    candidates: list[FieldMappingCandidate] = Field(default_factory=list)
    reason: str
    confidence: float
    recommended_action: str
    possible_consequences: str
    context: dict[str, Any] = Field(default_factory=dict)


class MigrationStats(BaseModel):
    files_ingested: int = 0
    total_source_rows: int = 0
    records_processed: int = 0
    records_cleaned: int = 0
    auto_mapped_fields: int = 0
    escalations_open: int = 0
    target_success: int = 0
    target_failed: int = 0
    progress_percent: float = 0.0
