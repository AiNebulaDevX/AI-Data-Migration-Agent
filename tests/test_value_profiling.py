import pandas as pd
from backend.profiling.value_analyzer import profile_dataframe, ValuePatternDetector


def test_email_pattern_detection():
    """Test that email patterns are correctly detected."""
    df = pd.DataFrame({
        'email': ['john@example.com', 'jane@test.org', 'bob@company.com']
    })
    profiles = profile_dataframe(df)
    email_profile = profiles['email']
    
    assert 'email' in email_profile.patterns
    assert email_profile.inferred_type == 'email'
    assert email_profile.unique_ratio == 1.0


def test_currency_pattern_detection():
    """Test that currency patterns are correctly detected."""
    df = pd.DataFrame({
        'salary': ['85000', '92000', '88000', '75000']
    })
    profiles = profile_dataframe(df)
    salary_profile = profiles['salary']
    
    assert 'currency' in salary_profile.patterns
    assert salary_profile.is_numeric is True
    assert salary_profile.numeric_stats is not None
    assert 70000 <= salary_profile.numeric_stats['min'] <= 100000


def test_person_name_pattern_detection():
    """Test that person name patterns are correctly detected."""
    df = pd.DataFrame({
        'name': ['John Smith', 'Jane Doe', 'Bob Johnson']
    })
    profiles = profile_dataframe(df)
    name_profile = profiles['name']
    
    assert 'person_name' in name_profile.patterns
    assert name_profile.inferred_type == 'string'


def test_integer_id_pattern_detection():
    """Test that integer ID patterns are correctly detected."""
    df = pd.DataFrame({
        'worker_no': ['101', '102', '103', '104']
    })
    profiles = profile_dataframe(df)
    id_profile = profiles['worker_no']
    
    assert 'integer_id' in id_profile.patterns
    assert id_profile.is_numeric is True


def test_date_pattern_detection():
    """Test that date patterns are correctly detected."""
    df = pd.DataFrame({
        'join_date': ['2020-01-15', '2019-06-20', '2021-03-10']
    })
    profiles = profile_dataframe(df)
    date_profile = profiles['join_date']
    
    assert 'date' in date_profile.patterns
    assert date_profile.inferred_type == 'date'


def test_reject_incompatible_patterns():
    """Test that incompatible patterns are rejected."""
    # Salary should not match email pattern
    assert not ValuePatternDetector.detect_email('85000')
    assert not ValuePatternDetector.detect_email('92000')
    
    # Email should not match currency pattern  
    assert not ValuePatternDetector.detect_currency('john@example.com')
    
    # Person name should not match integer ID pattern
    assert not ValuePatternDetector.detect_integer_id('John Smith')


if __name__ == '__main__':
    test_email_pattern_detection()
    test_currency_pattern_detection()
    test_person_name_pattern_detection()
    test_integer_id_pattern_detection()
    test_date_pattern_detection()
    test_reject_incompatible_patterns()
    print("All value profiling tests passed!")