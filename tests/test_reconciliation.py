from backend.reconciliation.merge import merge_records


def test_duplicate_merge_conflict():
    existing = {"employee_id": "EMP-102", "email": "a@b.com", "date_of_birth": "1995-02-01"}
    incoming = {"email": "a@b.com", "date_of_birth": "1995-01-02"}
    merged, conflicts = merge_records(existing, incoming, "crm.xlsx")
    assert conflicts
    assert "date_of_birth" in conflicts[0]
