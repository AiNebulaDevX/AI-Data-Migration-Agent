from backend.validation.employee_validator import validate_employee_payload


def test_validation_success():
    data = {
        "employee_id": "EMP-101",
        "first_name": "John",
        "last_name": "Smith",
        "email": "john@acme.com",
        "date_of_birth": "1990-05-15",
    }
    record, err = validate_employee_payload(data)
    assert record is not None
    assert err is None


def test_validation_failure_email():
    data = {
        "employee_id": "EMP-107",
        "first_name": "Bad",
        "last_name": "Email",
        "email": "not-an-email",
        "date_of_birth": "1990-01-01",
    }
    record, err = validate_employee_payload(data)
    assert record is None
    assert err
