from __future__ import annotations

import re
from typing import Any, Optional

from rapidfuzz import fuzz

from backend.models.schemas import FieldMappingCandidate, TargetSchemaField
from backend.profiling.value_analyzer import ColumnProfile, ValuePatternDetector
from backend.mapping.semantic_rules import is_semantically_compatible, filter_candidates_by_semantics

# Synonym groups for semantic matching (deterministic baseline)
FIELD_SYNONYMS: dict[str, set[str]] = {
    "employee_id": {"employee_id", "emp_id", "empid", "id", "employee_number", "employeenumber", "worker_no", "worker_no", "employee_id"},
    "first_name": {"first_name", "firstname", "givenname", "given_name", "fname"},
    "last_name": {"last_name", "lastname", "surname", "family_name", "lname"},
    "full_name": {"full_name", "fullname", "name", "employee_name"},
    "email": {"email", "email_address", "mail", "work_email", "mail"},
    "phone": {"phone", "phone_num", "phone_number", "mobile", "telephone"},
    "date_of_birth": {"date_of_birth", "dob", "birth_date", "dateofbirth", "birthdate", "DateOfBirth"},
    "department": {"department", "dept", "dept_name", "division", "team"},
    "job_title": {"job_title", "title", "job", "position", "role"},
    "hire_date": {"hire_date", "start_date", "employment_date", "joined", "doj", "joining_date"},
    "salary": {"salary", "annual_salary", "pay", "compensation", "wage"},
}


def _normalize_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _datatype_hint(values: list[str]) -> str:
    if not values:
        return "unknown"
    email_hits = sum(1 for v in values if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v.strip(), re.I))
    if email_hits >= max(1, len(values) // 2):
        return "email"
    date_hits = sum(1 for v in values if _looks_like_date(v))
    if date_hits >= max(1, len(values) // 2):
        return "date"
    id_hits = sum(1 for v in values if re.match(r"^EMP-[A-Z0-9]+$", v.strip()))
    if id_hits >= max(1, len(values) // 2):
        return "id"
    return "string"


def _looks_like_date(value: str) -> bool:
    v = value.strip()
    patterns = [
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{2}/\d{2}/\d{4}$",
        r"^\d{2}-\d{2}-\d{4}$",
        r"^\d{1,2}/\d{1,2}/\d{4}$",
    ]
    return any(re.match(p, v) for p in patterns)


def score_mapping(
    source_column: str,
    target_field: str,
    target_meta: TargetSchemaField,
    sample_values: list[str],
    column_profile: Optional[ColumnProfile] = None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    norm_src = _normalize_col(source_column)
    norm_tgt = _normalize_col(target_field)

    # 1. Semantic similarity (30%)
    name_score = fuzz.token_sort_ratio(norm_src, norm_tgt) / 100.0
    synonym_hit = norm_src in {_normalize_col(s) for s in FIELD_SYNONYMS.get(target_field, set())}
    if synonym_hit:
        name_score = 1.0
        reasons.append("Column name matches known synonym for target field")
    elif name_score >= 0.8:
        reasons.append("Column name strongly matches target field name")
    elif name_score >= 0.5:
        reasons.append("Partial column name similarity")

    # 2. Value pattern compatibility (25%)
    pattern_score = 0.5
    if column_profile:
        patterns = column_profile.patterns
        
        # Check pattern compatibility with target field
        if target_field == "email" and "email" in patterns:
            pattern_score = 1.0
            reasons.append("Values match email pattern")
        elif target_field == "phone" and "phone" in patterns:
            pattern_score = 1.0
            reasons.append("Values match phone pattern")
        elif target_field == "date_of_birth" and "date" in patterns:
            pattern_score = 1.0
            reasons.append("Values match date pattern")
        elif target_field == "hire_date" and "date" in patterns:
            pattern_score = 1.0
            reasons.append("Values match date pattern")
        elif target_field == "salary" and "currency" in patterns:
            pattern_score = 1.0
            reasons.append("Values match currency pattern")
        elif target_field == "employee_id" and "integer_id" in patterns:
            pattern_score = 1.0
            reasons.append("Values match integer ID pattern")
        elif target_field in ["first_name", "last_name", "full_name"] and "person_name" in patterns:
            pattern_score = 0.9
            reasons.append("Values match person name pattern")
        
        # Reject incompatible patterns
        if target_field == "email" and patterns and "email" not in patterns:
            if "currency" in patterns or "integer_id" in patterns:
                pattern_score = 0.0
                reasons.append("Values are not email-like")
        elif target_field in ["first_name", "last_name", "full_name"] and patterns:
            if "currency" in patterns or "integer_id" in patterns or "email" in patterns:
                pattern_score = 0.0
                reasons.append("Values are not name-like")
        elif target_field == "salary" and patterns:
            if "email" in patterns or "person_name" in patterns:
                pattern_score = 0.0
                reasons.append("Values are not currency-like")

    # 3. Datatype compatibility (20%)
    expected_type = target_meta.type
    inferred = _datatype_hint(sample_values)
    type_score = 0.5
    if expected_type == "email" and inferred == "email":
        type_score = 1.0
        reasons.append("Sample values match expected email format")
    elif expected_type == "date" and inferred == "date":
        type_score = 1.0
        reasons.append("Sample values look like dates")
    elif expected_type == "string" and inferred == "string":
        type_score = 0.85
        reasons.append("String datatype compatible")
    elif expected_type == "string" and inferred == "id" and target_field == "employee_id":
        type_score = 1.0
        reasons.append("Values match employee ID pattern")
    else:
        reasons.append("Datatype compatibility uncertain")

    # 4. Statistical compatibility (15%)
    stat_score = 0.5
    if column_profile and column_profile.is_numeric:
        if target_field == "salary":
            # Salary should be in reasonable range
            if column_profile.numeric_stats:
                min_val = column_profile.numeric_stats.get("min", 0)
                max_val = column_profile.numeric_stats.get("max", 0)
                if 20000 <= min_val <= 500000 and 20000 <= max_val <= 500000:
                    stat_score = 1.0
                    reasons.append("Numeric values in salary range")
                else:
                    stat_score = 0.0
                    reasons.append("Numeric values outside salary range")
        elif target_field in ["first_name", "last_name", "full_name", "email", "phone"]:
            stat_score = 0.0
            reasons.append("Numeric values incompatible with text field")
    elif column_profile and not column_profile.is_numeric:
        if target_field == "salary":
            stat_score = 0.0
            reasons.append("Non-numeric values incompatible with salary field")

    # 5. Cross-file correlation placeholder (10%)
    correlation_score = 0.5  # Will be enhanced with actual cross-file analysis

    # Multi-signal confidence calculation
    confidence = (
        0.30 * name_score +
        0.25 * pattern_score +
        0.20 * type_score +
        0.15 * stat_score +
        0.10 * correlation_score
    )

    # Boost for known synonyms, but cap at reasonable values
    if synonym_hit:
        confidence = min(confidence + 0.15, 0.98)  # Add boost but cap at 98%

    # Special handling for ambiguous 'name' column
    if norm_src == "name":
        if target_field == "full_name":
            confidence = min(confidence, 0.78)
        if target_field == "first_name":
            confidence = max(confidence, 0.72)

    # Reject obviously impossible mappings
    if pattern_score == 0.0 or stat_score == 0.0:
        confidence = min(confidence, 0.1)  # Very low confidence for incompatible patterns

    confidence = round(min(0.99, max(0.0, confidence)), 4)
    return confidence, reasons


def rank_target_candidates(
    source_column: str,
    target_fields: dict[str, TargetSchemaField],
    sample_values: list[str],
    column_profile: Optional[ColumnProfile] = None,
) -> tuple[list[FieldMappingCandidate], list[dict]]:
    """
    Rank target candidates with semantic filtering.
    
    Returns:
        (compatible_candidates, incompatible_candidates_with_reasons)
    """
    source_semantic_type = column_profile.semantic_type if column_profile else "text"
    
    # Generate all initial candidates
    all_candidates: list[FieldMappingCandidate] = []
    for field_name, meta in target_fields.items():
        conf, reasons = score_mapping(source_column, field_name, meta, sample_values, column_profile)
        all_candidates.append(FieldMappingCandidate(target_field=field_name, confidence=conf, reasons=reasons))
    
    # Filter by semantic compatibility
    compatible, incompatible = filter_candidates_by_semantics(
        source_column, source_semantic_type, all_candidates
    )
    
    # Sort compatible candidates by confidence
    compatible.sort(key=lambda c: c.confidence, reverse=True)
    
    return compatible, incompatible


def should_escalate_mapping(
    source_column: str,
    candidates: list[FieldMappingCandidate],
    incompatible_candidates: list[dict],
    threshold: float,
    gap: float,
    column_profile: Optional[ColumnProfile] = None,
) -> tuple[bool, str, bool, str]:  # Added decision_type: "AUTO_MAP", "ESCALATE", "REJECT"
    """
    Three-tier decision system for mapping recommendations.
    
    Returns:
        (should_escalate, reason, should_reject, decision_type)
    """
    if not candidates and not incompatible_candidates:
        return True, "No mapping candidates found", False, "ESCALATE"
    
    # If we have no compatible candidates but have incompatible ones, this is a REJECT case
    if not candidates and incompatible_candidates:
        incompatible_reason = incompatible_candidates[0]["reason"]
        return False, incompatible_reason, True, "REJECT"
    
    if not candidates:
        return True, "No compatible mapping candidates found", False, "ESCALATE"
    
    # If we have compatible candidates, proceed with them (ignore incompatible ones)
    top = candidates[0]
    norm_src = _normalize_col(source_column)
    full = next((c for c in candidates if c.target_field == "full_name"), None)
    first = next((c for c in candidates if c.target_field == "first_name"), None)
    
    # Special handling for 'name' column ambiguity
    if norm_src == "name" and full and first:
        return True, (
            "Source column 'name' does not provide enough evidence to determine "
            f"whether values represent full_name ({full.confidence:.0%}) or first_name ({first.confidence:.0%})"
        ), False, "ESCALATE"
    
    # High confidence auto-mapping
    if top.confidence >= 0.90:
        return False, f"High confidence mapping ({top.confidence:.0%})", False, "AUTO_MAP"
    
    second = candidates[1] if len(candidates) > 1 else None
    if top.confidence < threshold:
        if second and (top.confidence - second.confidence) < gap:
            return True, (
                f"Top candidates {top.target_field} ({top.confidence:.0%}) and "
                f"{second.target_field} ({second.confidence:.0%}) are too close"
            ), False, "ESCALATE"
        if top.confidence < threshold:
            return True, f"Confidence {top.confidence:.0%} below autonomous threshold {threshold:.0%}", False, "ESCALATE"
    
    if second and (top.confidence - second.confidence) < gap and top.confidence < 0.95:
        pair = {top.target_field, second.target_field}
        if pair == {"full_name", "first_name"}:
            return True, (
                f"Source column may represent full name or given name only "
                f"({top.target_field} {top.confidence:.0%} vs {second.target_field} {second.confidence:.0%})"
            ), False, "ESCALATE"
        return True, (
            f"Competing target fields: {top.target_field} vs {second.target_field} "
            f"(gap {(top.confidence - second.confidence):.0%})"
        ), False, "ESCALATE"
    
    # Default to auto-map for remaining high-confidence cases
    return False, f"Confidence {top.confidence:.0%} meets threshold", False, "AUTO_MAP"
