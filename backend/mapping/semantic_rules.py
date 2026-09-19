"""Hard incompatibility rules for semantic mapping validation."""

# Target field semantic types
TARGET_SEMANTIC_TYPES = {
    "employee_id": "identifier",
    "first_name": "person_name",
    "last_name": "person_name", 
    "full_name": "person_name",
    "email": "email",
    "phone": "phone",
    "date_of_birth": "date",
    "department": "department",
    "job_title": "job_title",
    "hire_date": "date",
    "salary": "currency_amount",
}

# Hard incompatibility rules: source_semantic_type cannot map to target_semantic_type
INCOMPATIBLE_MAPPINGS = {
    "currency_amount": ["person_name", "email", "date", "identifier", "phone"],
    "email": ["currency_amount", "identifier", "date", "person_name", "phone"],
    "phone": ["currency_amount", "email", "date", "identifier", "person_name"],
    "date": ["currency_amount", "email", "person_name", "identifier", "phone"],
    "person_name": ["currency_amount", "email", "date", "identifier", "phone"],
    "identifier": ["currency_amount", "email", "date", "person_name", "phone"],
    "boolean": ["currency_amount", "email", "date", "person_name", "identifier", "phone"],
    "url": ["currency_amount", "email", "date", "person_name", "identifier", "phone"],
    "postal_code": ["currency_amount", "email", "date", "person_name", "identifier", "phone"],
}

def is_semantically_compatible(source_semantic_type: str, target_field: str) -> tuple[bool, str]:
    """
    Check if a source semantic type is compatible with a target field.
    
    Returns:
        (is_compatible, reason)
    """
    target_semantic_type = TARGET_SEMANTIC_TYPES.get(target_field, "text")
    
    # If semantic types match, they're compatible
    if source_semantic_type == target_semantic_type:
        return True, f"Semantic types match: {source_semantic_type}"
    
    # If source semantic type is unknown/text, be more permissive
    if source_semantic_type in ["text", "unknown", "numeric"]:
        # Allow text/numeric to map to most fields unless there's a strong reason not to
        return True, f"Flexible mapping allowed: {source_semantic_type} → {target_semantic_type}"
    
    # Check hard incompatibility rules
    incompatible_targets = INCOMPATIBLE_MAPPINGS.get(source_semantic_type, [])
    if target_semantic_type in incompatible_targets:
        return False, f"Semantic incompatibility: {source_semantic_type} cannot map to {target_semantic_type}"
    
    # Allow some flexible mappings
    flexible_mappings = {
        "text": ["department", "job_title", "identifier"],  # Text can map to categorical/ID fields
        "numeric": ["identifier"],  # Numeric can be identifier if small integers
        "department": ["text"],  # Department can be text
        "job_title": ["text"],  # Job title can be text
    }
    
    if source_semantic_type in flexible_mappings:
        if target_semantic_type in flexible_mappings[source_semantic_type]:
            return True, f"Flexible mapping allowed: {source_semantic_type} → {target_semantic_type}"
    
    # Default to compatible for unknown combinations (be permissive)
    return True, f"Default compatibility: {source_semantic_type} → {target_semantic_type}"


def filter_candidates_by_semantics(
    source_column: str,
    source_semantic_type: str,
    candidates: list,
) -> tuple[list, list]:
    """
    Filter candidates based on semantic compatibility.
    
    Returns:
        (compatible_candidates, incompatible_candidates)
    """
    compatible = []
    incompatible = []
    
    # Support both (source_column, source_semantic_type) and (source_semantic_type, source_column)
    if source_column in TARGET_SEMANTIC_TYPES.values() or source_column in INCOMPATIBLE_MAPPINGS:
        sem_type = source_column
    else:
        sem_type = source_semantic_type
    
    for candidate in candidates:
        target_field = candidate.target_field
        is_compatible, reason = is_semantically_compatible(sem_type, target_field)
        
        if is_compatible:
            compatible.append(candidate)
        else:
            # Mark incompatible candidates with rejection reason
            incompatible.append({
                "candidate": candidate,
                "reason": reason
            })
    
    return compatible, incompatible