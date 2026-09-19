from backend.mapping.confidence import rank_target_candidates, should_escalate_mapping
from backend.validation.employee_validator import load_target_schema


def test_field_mapping_employee_id():
    schema = load_target_schema()
    from backend.profiling.value_analyzer import ColumnProfile
    profile = ColumnProfile(
        column="empId",
        inferred_type="string",
        sample_values=["EMP-101", "EMP-102"],
        unique_count=2,
        total_count=2,
        unique_ratio=1.0,
        null_ratio=0.0,
        patterns=["integer_id"],
        is_numeric=False,
        semantic_type="identifier"
    )
    candidates, incompatible = rank_target_candidates("empId", schema, ["EMP-101", "EMP-102"], profile)
    assert candidates[0].target_field == "employee_id"
    assert candidates[0].confidence >= 0.85
    escalate, _, should_reject, decision_type = should_escalate_mapping("empId", candidates, incompatible, 0.85, 0.12)
    assert escalate is False
    assert should_reject is False
    assert decision_type == "AUTO_MAP"


def test_ambiguous_name_mapping_escalates():
    schema = load_target_schema()
    from backend.profiling.value_analyzer import ColumnProfile
    profile = ColumnProfile(
        column="Name",
        inferred_type="string",
        sample_values=["Rahul", "John"],  # Single names to trigger ambiguity
        unique_count=2,
        total_count=2,
        unique_ratio=1.0,
        null_ratio=0.0,
        patterns=["person_name"],
        is_numeric=False,
        semantic_type="person_name"
    )
    candidates, incompatible = rank_target_candidates("Name", schema, ["Rahul", "John"], profile)
    escalate, reason, should_reject, decision_type = should_escalate_mapping("Name", candidates, incompatible, 0.85, 0.12)
    assert escalate is True
    assert "full_name" in reason and "first_name" in reason
    assert should_reject is False
    assert decision_type == "ESCALATE"


def test_synonym_mapping_auto_approved():
    schema = load_target_schema()
    from backend.profiling.value_analyzer import ColumnProfile
    profile = ColumnProfile(
        column="givenName",
        inferred_type="string",
        sample_values=["John", "Maria"],
        unique_count=2,
        total_count=2,
        unique_ratio=1.0,
        null_ratio=0.0,
        patterns=["person_name"],
        is_numeric=False,
        semantic_type="person_name"
    )
    candidates, incompatible = rank_target_candidates("givenName", schema, ["John", "Maria"], profile)
    assert candidates[0].target_field == "first_name"
    assert candidates[0].confidence >= 0.94
    escalate, _, should_reject, decision_type = should_escalate_mapping("givenName", candidates, incompatible, 0.85, 0.12)
    assert escalate is False
    assert should_reject is False
    assert decision_type == "AUTO_MAP"


def test_salary_not_mapped_to_name():
    """Test that salary columns filter out incompatible name fields."""
    schema = load_target_schema()
    from backend.profiling.value_analyzer import ColumnProfile
    profile = ColumnProfile(
        column="salary",
        inferred_type="numeric",
        sample_values=["85000", "92000", "88000"],
        unique_count=3,
        total_count=3,
        unique_ratio=1.0,
        null_ratio=0.0,
        patterns=["currency"],
        is_numeric=True,
        numeric_stats={"min": 85000, "max": 92000, "mean": 88333, "std": 3512},
        semantic_type="currency_amount"
    )
    candidates, incompatible = rank_target_candidates("salary", schema, ["85000", "92000", "88000"], profile)
    
    # Salary should not map to name fields - they should be filtered as incompatible
    name_incompatible = [inc for inc in incompatible if inc["candidate"].target_field in ["first_name", "last_name", "full_name"]]
    assert len(name_incompatible) > 0, "Salary mappings to name fields should be marked as incompatible"
    
    # The compatible candidates should not include name fields
    compatible_targets = [c.target_field for c in candidates]
    assert "first_name" not in compatible_targets
    assert "last_name" not in compatible_targets
    assert "full_name" not in compatible_targets
    
    # Test that numeric salary values don't map to email field in compatible candidates
    email_incompatible = [inc for inc in incompatible if inc["candidate"].target_field == "email"]
    assert len(email_incompatible) > 0, "Salary mapping to email should be marked as incompatible"
    assert "email" not in compatible_targets
