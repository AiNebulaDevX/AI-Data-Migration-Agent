from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional
from collections import Counter
import pandas as pd


@dataclass
class ColumnProfile:
    column: str
    inferred_type: str
    sample_values: list[str]
    unique_count: int
    total_count: int
    unique_ratio: float
    null_ratio: float
    patterns: list[str]
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    avg_length: Optional[float] = None
    is_numeric: bool = False
    numeric_stats: Optional[dict[str, float]] = None
    semantic_type: Optional[str] = None  # NEW: Add semantic classification


class ValuePatternDetector:
    """Deterministic detectors for common data patterns."""
    
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    PHONE_PATTERN = re.compile(r'^[\d\s\-\(\)\+]{10,15}$')
    DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$|^\d{2}/\d{2}/\d{4}$|^\d{2}-\d{2}-\d{4}$|^\d{1,2}/\d{1,2}/\d{4}$')
    INTEGER_ID_PATTERN = re.compile(r'^\d{3,}$')
    URL_PATTERN = re.compile(r'^https?://[^\s/$.?#].[^\s]*$')
    POSTAL_CODE_PATTERN = re.compile(r'^\d{5}(-\d{4})?$|^[A-Za-z]\d[A-Za-z] \d[A-Za-z]\d$')
    BOOLEAN_PATTERN = re.compile(r'^(true|false|yes|no|1|0)$', re.IGNORECASE)
    
    @classmethod
    def detect_email(cls, value: str) -> bool:
        return bool(cls.EMAIL_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_phone(cls, value: str) -> bool:
        return bool(cls.PHONE_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_date(cls, value: str) -> bool:
        return bool(cls.DATE_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_integer_id(cls, value: str) -> bool:
        return bool(cls.INTEGER_ID_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_url(cls, value: str) -> bool:
        return bool(cls.URL_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_postal_code(cls, value: str) -> bool:
        return bool(cls.POSTAL_CODE_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_boolean(cls, value: str) -> bool:
        return bool(cls.BOOLEAN_PATTERN.match(str(value).strip()))
    
    @classmethod
    def detect_currency(cls, value: str) -> bool:
        """Detect currency-like numeric values."""
        val_str = str(value).strip()
        has_symbol = any(s in val_str for s in ('$', '€', '£', '¥'))
        try:
            num_str = val_str.replace(',', '').replace('$', '').replace('€', '').replace('£', '').replace('¥', '').strip()
            num = float(num_str)
            if has_symbol:
                return True
            if '.' in num_str and len(num_str.split('.')[1]) == 2:
                return True
            if 10000 <= num <= 10000000:
                return True
        except (ValueError, AttributeError):
            return False
        return False
    
    @classmethod
    def detect_person_name(cls, value: str) -> bool:
        """Detect person names (multi-word, capitalized)."""
        words = str(value).strip().split()
        if len(words) < 2 or len(words) > 4:
            return False
        # Check if words are capitalized
        return all(word and word[0].isupper() for word in words if word)


def classify_semantic_type(profile: ColumnProfile, column_name: str) -> str:
    """Classify the semantic meaning of a column based on patterns and statistics."""
    patterns = profile.patterns
    is_numeric = profile.is_numeric
    numeric_stats = profile.numeric_stats
    sample_values = profile.sample_values
    
    # Column name-based classification - HIGH PRIORITY for strong semantic indicators
    norm_name = column_name.lower().replace("_", "").replace(" ", "")
    
    # Salary/compensation detection - highest priority due to business importance
    if any(term in norm_name for term in ["salary", "pay", "wage", "compensation", "annual", "income"]):
        if is_numeric and numeric_stats:
            min_val = numeric_stats.get("min", 0)
            max_val = numeric_stats.get("max", 0)
            # Salary range detection with reasonable bounds
            if 10000 <= min_val <= 1000000 and 10000 <= max_val <= 1000000:
                return "currency_amount"
        # Even if not numeric, if column name strongly suggests salary, mark it
        return "currency_amount"
    
    # Employee ID detection - high priority
    if any(term in norm_name for term in ["employee_id", "empid", "emp_id", "employeeid", "worker_no", "workerno"]):
        return "identifier"
    
    # Date field detection from column name
    if any(term in norm_name for term in ["dob", "dateofbirth", "birthdate", "birth_date"]):
        return "date"
    if any(term in norm_name for term in ["hire_date", "startdate", "joining_date", "doj", "employment_date"]):
        return "date"
    
    # Email detection from column name
    if any(term in norm_name for term in ["email", "email_address", "mail"]):
        return "email"
    
    # Name detection from column name
    if any(term in norm_name for term in ["name", "fullname", "employee_name"]):
        if sample_values and any(" " in str(v) for v in sample_values[:3]):
            return "person_name"
        else:
            return "person_name"  # Default to person name for name columns
    
    # Department detection
    if any(term in norm_name for term in ["dept", "department", "team", "division", "unit"]):
        # Check if values are categorical codes (short strings, low unique ratio)
        if sample_values and len(sample_values) > 0:
            avg_length = sum(len(str(v)) for v in sample_values[:5]) / min(5, len(sample_values))
            if avg_length < 10 and profile.unique_ratio < 0.8:  # Short codes, not unique per row
                return "categorical"
        return "department"
    
    # Job title detection
    if any(term in norm_name for term in ["title", "role", "position", "job"]):
        return "job_title"
    
    # Phone detection from column name
    if any(term in norm_name for term in ["phone", "mobile", "telephone"]):
        return "phone"
    
    # Generic ID detection
    if any(term in norm_name for term in ["id", "no", "num", "worker", "emp"]):
        if is_numeric and numeric_stats:
            min_val = numeric_stats.get("min", 0)
            max_val = numeric_stats.get("max", 0)
            if min_val >= 0 and max_val < 10000 and profile.unique_ratio > 0.9:
                return "identifier"
    
    # Pattern-based classification (lower priority than column names)
    if "email" in patterns:
        return "email"
    elif "date" in patterns:
        return "date"
    elif "currency" in patterns:
        return "currency_amount"
    elif "phone" in patterns:
        return "phone"
    elif "person_name" in patterns:
        return "person_name"
    elif "integer_id" in patterns:
        return "identifier"
    elif "boolean" in patterns:
        return "boolean"
    elif "url" in patterns:
        return "url"
    elif "postal_code" in patterns:
        return "postal_code"
    
    # Default classification
    if is_numeric:
        return "numeric"
    return "text"


def analyze_column_values(column_name: str, series: pd.Series, sample_size: int = 20) -> ColumnProfile:
    """Analyze a column's values to extract patterns and statistics."""
    # Convert to string and clean
    values = series.astype(str).replace('nan', '').replace('None', '').replace('', pd.NA).dropna()
    
    if len(values) == 0:
        return ColumnProfile(
            column=column_name,
            inferred_type="empty",
            sample_values=[],
            unique_count=0,
            total_count=0,
            unique_ratio=0.0,
            null_ratio=1.0,
            patterns=[],
            semantic_type="empty"
        )
    
    total_count = len(values)
    unique_count = values.nunique()
    unique_ratio = unique_count / total_count if total_count > 0 else 0
    
    # Sample values
    sample_values = values.head(sample_size).tolist()
    
    # Detect patterns
    patterns = []
    pattern_counts = Counter()
    
    for val in values.head(100):  # Check first 100 values for patterns
        detected = []
        # Priority-based detection - check more specific patterns first
        if ValuePatternDetector.detect_email(val):
            detected.append("email")
        elif ValuePatternDetector.detect_date(val):
            detected.append("date")
        elif ValuePatternDetector.detect_currency(val):
            detected.append("currency")
        elif ValuePatternDetector.detect_phone(val):
            detected.append("phone")
        elif ValuePatternDetector.detect_integer_id(val):
            detected.append("integer_id")
        elif ValuePatternDetector.detect_url(val):
            detected.append("url")
        elif ValuePatternDetector.detect_postal_code(val):
            detected.append("postal_code")
        elif ValuePatternDetector.detect_boolean(val):
            detected.append("boolean")
        elif ValuePatternDetector.detect_person_name(val):
            detected.append("person_name")
        
        for pattern in detected:
            pattern_counts[pattern] += 1
    
    # Keep patterns that appear in at least 20% of checked values
    if total_count > 0:
        patterns = [p for p, count in pattern_counts.items() if count / min(100, total_count) >= 0.2]
    
    # Numeric analysis
    is_numeric = False
    numeric_stats = None
    try:
        numeric_values = pd.to_numeric(values, errors='coerce').dropna()
        if len(numeric_values) > 0:
            is_numeric = True
            numeric_stats = {
                "min": float(numeric_values.min()),
                "max": float(numeric_values.max()),
                "mean": float(numeric_values.mean()),
                "std": float(numeric_values.std()) if len(numeric_values) > 1 else 0.0
            }
    except Exception:
        pass
    
    # String length analysis
    avg_length = None
    try:
        avg_length = values.str.len().mean()
    except Exception:
        pass
    
    # Infer type
    inferred_type = "string"
    if is_numeric:
        inferred_type = "numeric"
    elif "email" in patterns:
        inferred_type = "email"
    elif "date" in patterns:
        inferred_type = "date"
    elif "boolean" in patterns:
        inferred_type = "boolean"
    
    # Create temporary profile for semantic classification
    temp_profile = ColumnProfile(
        column=column_name,
        inferred_type=inferred_type,
        sample_values=sample_values,
        unique_count=unique_count,
        total_count=total_count,
        unique_ratio=unique_ratio,
        null_ratio=series.isna().sum() / len(series) if len(series) > 0 else 0,
        patterns=patterns,
        min_value=str(values.min()) if len(values) > 0 else None,
        max_value=str(values.max()) if len(values) > 0 else None,
        avg_length=avg_length,
        is_numeric=is_numeric,
        numeric_stats=numeric_stats,
        semantic_type=None
    )
    
    # Classify semantic type
    semantic_type = classify_semantic_type(temp_profile, column_name)
    temp_profile.semantic_type = semantic_type
    
    return temp_profile


def profile_dataframe(df: pd.DataFrame) -> dict[str, ColumnProfile]:
    """Profile all columns in a dataframe."""
    profiles = {}
    for column in df.columns:
        profiles[column] = analyze_column_values(column, df[column])
    return profiles