from backend.mapping.semantic_rules import is_semantically_compatible, filter_candidates_by_semantics
from backend.models.schemas import FieldMappingCandidate


def test_currency_incompatible_with_person_name():
    """Test that currency amounts are incompatible with person names."""
    is_compatible, reason = is_semantically_compatible("currency_amount", "first_name")
    assert is_compatible is False
    assert "incompatibility" in reason.lower()


def test_email_incompatible_with_identifier():
    """Test that email is incompatible with identifier."""
    is_compatible, reason = is_semantically_compatible("email", "employee_id")
    assert is_compatible is False
    assert "incompatibility" in reason.lower()


def test_identifier_incompatible_with_email():
    """Test that identifiers are incompatible with email."""
    is_compatible, reason = is_semantically_compatible("identifier", "email")
    assert is_compatible is False
    assert "incompatibility" in reason.lower()


def test_matching_semantic_types_compatible():
    """Test that matching semantic types are compatible."""
    is_compatible, reason = is_semantically_compatible("email", "email")
    assert is_compatible is True
    assert "match" in reason.lower()


def test_filter_candidates_removes_incompatible():
    """Test that filtering removes incompatible candidates."""
    candidates = [
        FieldMappingCandidate(target_field="first_name", confidence=0.9, reasons=["test"]),
        FieldMappingCandidate(target_field="last_name", confidence=0.8, reasons=["test"]),
        FieldMappingCandidate(target_field="email", confidence=0.7, reasons=["test"]),
    ]
    
    compatible, incompatible = filter_candidates_by_semantics("currency_amount", "salary", candidates)
    
    # Person names should be filtered out as incompatible
    person_name_incompatible = [inc for inc in incompatible if inc["candidate"].target_field in ["first_name", "last_name"]]
    assert len(person_name_incompatible) == 2, "Person name fields should be incompatible with currency"
    
    # Email should also be incompatible
    email_incompatible = [inc for inc in incompatible if inc["candidate"].target_field == "email"]
    assert len(email_incompatible) == 1, "Email should be incompatible with currency"


def test_department_codes_compatible_with_department():
    """Test that department codes can map to department field."""
    is_compatible, reason = is_semantically_compatible("text", "department")
    assert is_compatible is True
    assert "Flexible" in reason or "match" in reason.lower()


if __name__ == '__main__':
    test_currency_incompatible_with_person_name()
    test_email_incompatible_with_salary()
    test_identifier_incompatible_with_email()
    test_matching_semantic_types_compatible()
    test_filter_candidates_removes_incompatible()
    test_department_codes_compatible_with_department()
    print("All semantic rule tests passed!")