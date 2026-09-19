"""Cross-file evidence collection for resolving ambiguous data."""

from typing import Any, Dict, Optional
import re


class CrossFileEvidence:
    """Collects evidence across source files to resolve ambiguities."""
    
    @staticmethod
    def resolve_date_ambiguity(
        ambiguous_date: str, 
        employee_id: str, 
        all_source_data: Dict[str, Any]
    ) -> tuple[Optional[str], str, float]:
        """
        Resolve ambiguous date formats using cross-file evidence.
        
        Args:
            ambiguous_date: The ambiguous date (e.g., "01/02/1995")
            employee_id: The employee identifier
            all_source_data: All source data from multiple files
            
        Returns:
            (resolved_date, reason, confidence)
        """
        # Look for same employee in other files with clearer date formats
        for file_data in all_source_data.values():
            for record in file_data:
                if record.get("employee_id") == employee_id or record.get("empId") == employee_id:
                    # Check for ISO format dates (unambiguous)
                    for date_field in ["hire_date", "joining_date", "start_date", "birth_date", "dob"]:
                        date_value = record.get(date_field)
                        if date_value and re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_value)):
                            # This is an unambiguous ISO date
                            return str(date_value), f"Cross-file evidence: unambiguous ISO date found in {date_field}", 0.99
        
        # Try to infer format from other dates in the same file
        # If most dates are DD/MM/YYYY, assume that format
        # If most dates are MM/DD/YYYY, assume that format
        for file_data in all_source_data.values():
            date_formats = []
            for record in file_data:
                for date_field in ["hire_date", "joining_date", "start_date", "birth_date", "dob"]:
                    date_value = record.get(date_field)
                    if date_value and re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', str(date_value)):
                        # Try to infer format from the date
                        parts = str(date_value).split('/')
                        if len(parts) == 3:
                            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                            if month > 12:  # First part can't be month, must be day
                                date_formats.append("DMY")
                            elif day > 12:  # Second part can't be day, must be month
                                date_formats.append("MDY")
            
            if date_formats:
                most_common = max(set(date_formats), key=date_formats.count)
                if most_common == "DMY":
                    # Convert DMY to ISO
                    parts = ambiguous_date.split('/')
                    iso_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    return iso_date, f"Inferred DMY format from file pattern analysis", 0.85
                elif most_common == "MDY":
                    # Convert MDY to ISO
                    parts = ambiguous_date.split('/')
                    iso_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    return iso_date, f"Inferred MDY format from file pattern analysis", 0.85
        
        return None, "No cross-file evidence available for date disambiguation", 0.0