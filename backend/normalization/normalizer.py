"""Normalization layer for handling representation differences in data migration."""

from typing import Any, Optional
import re


class ValueNormalizer:
    """Normalizes values to canonical representations for comparison."""
    
    # Department code mappings
    DEPARTMENT_CODES = {
        "ENG": "Engineering",
        "FIN": "Finance", 
        "HR": "Human Resources",
        "MKT": "Marketing",
        "OPS": "Operations",
        "R&D": "Research and Development",
        "IT": "Information Technology",
        "SALES": "Sales",
    }
    
    # Common abbreviations to full forms
    COMMON_ABBREVIATIONS = {
        "Corp": "Corporation",
        "Inc": "Incorporated", 
        "Ltd": "Limited",
        "Co": "Company",
        "Mgr": "Manager",
        "Dir": "Director",
        "VP": "Vice President",
        "Sr": "Senior",
        "Jr": "Junior",
    }
    
    @classmethod
    def normalize_department(cls, value: str) -> str:
        """Normalize department codes and abbreviations to canonical form."""
        if not value:
            return value
        
        value = str(value).strip()
        
        # Handle common department codes
        if value in cls.DEPARTMENT_CODES:
            return cls.DEPARTMENT_CODES[value]
        
        # Handle case variations
        if value.lower() in [k.lower() for k in cls.DEPARTMENT_CODES.keys()]:
            for code, full_name in cls.DEPARTMENT_CODES.items():
                if code.lower() == value.lower():
                    return full_name
        
        return value
    
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email addresses to lowercase."""
        if not value:
            return value
        return str(value).strip().lower()
    
    @classmethod
    def normalize_date(cls, value: str) -> str:
        """Normalize various date formats to ISO-8601 (YYYY-MM-DD)."""
        if not value:
            return value
        
        value = str(value).strip()
        
        # If already in ISO format, return as-is
        if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
            return value
        
        # Try to parse common formats
        for pattern, converter in [
            (r'^(\d{1,2})/(\d{1,2})/(\d{4})$', cls._convert_mdy_to_iso),
            (r'^(\d{4})-(\d{1,2})-(\d{1,2})$', lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"),
            (r'^(\d{1,2})-(\d{1,2})-(\d{4})$', cls._convert_dmy_to_iso),
        ]:
            match = re.match(pattern, value)
            if match:
                try:
                    return converter(match)
                except (ValueError, IndexError):
                    pass
        
        return value  # Return original if can't normalize
    
    @classmethod
    def _convert_mdy_to_iso(cls, match) -> str:
        """Convert MM/DD/YYYY to YYYY-MM-DD."""
        month, day, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    
    @classmethod
    def _convert_dmy_to_iso(cls, match) -> str:
        """Convert DD-MM-YYYY to YYYY-MM-DD."""
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    
    @classmethod
    def normalize_salary(cls, value: Any) -> Optional[float]:
        """Normalize salary to numeric format."""
        if value is None:
            return None
        
        # Remove currency symbols and commas
        if isinstance(value, str):
            value = value.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip()
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    @classmethod
    def normalize_employee_id(cls, value: str) -> str:
        """Normalize employee ID to standard format if possible."""
        if not value:
            return value
        
        value = str(value).strip()
        
        # If already in EMP-XXXX format, return as-is
        if re.match(r'^EMP-[A-Z0-9]+$', value):
            return value
        
        # If it's a numeric ID, potentially transform to EMP-XXXX format
        if value.isdigit():
            # This is a candidate for transformation, but we don't auto-apply
            # Return as-is and let the transformation layer handle it
            return value
        
        return value


def compare_normalized_values(value1: str, value2: str, field_type: str) -> tuple[bool, str]:
    """
    Compare two values after normalization to detect if they're truly different.
    
    Returns:
        (is_different, reason)
    """
    if value1 == value2:
        return False, "Values are identical"
    
    # Apply field-specific normalization
    if field_type == "department":
        norm1 = ValueNormalizer.normalize_department(value1)
        norm2 = ValueNormalizer.normalize_department(value2)
        if norm1 == norm2:
            return False, f"Normalized department: {value1} → {norm1} == {value2} → {norm2}"
    
    elif field_type == "email":
        norm1 = ValueNormalizer.normalize_email(value1)
        norm2 = ValueNormalizer.normalize_email(value2)
        if norm1 == norm2:
            return False, f"Normalized email: {value1} → {norm1} == {value2} → {norm2}"
    
    elif field_type == "date":
        norm1 = ValueNormalizer.normalize_date(value1)
        norm2 = ValueNormalizer.normalize_date(value2)
        if norm1 == norm2:
            return False, f"Normalized date: {value1} → {norm1} == {value2} → {norm2}"
    
    elif field_type == "salary":
        num1 = ValueNormalizer.normalize_salary(value1)
        num2 = ValueNormalizer.normalize_salary(value2)
        if num1 is not None and num2 is not None and num1 == num2:
            return False, f"Normalized salary: {value1} → {num1} == {value2} → {num2}"
    
    return True, f"Values are genuinely different: {value1} vs {value2}"