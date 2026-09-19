import pandas as pd
from backend.profiling.value_analyzer import profile_dataframe


def test_salary_column_classification():
    """Test that salary columns are correctly classified as currency_amount."""
    df = pd.DataFrame({
        'salary': ['85000', '92000', '88000', '78000']
    })
    profiles = profile_dataframe(df)
    salary_profile = profiles['salary']
    
    print(f"Salary column semantic type: {salary_profile.semantic_type}")
    print(f"Salary column patterns: {salary_profile.patterns}")
    print(f"Salary column is_numeric: {salary_profile.is_numeric}")
    print(f"Salary column numeric_stats: {salary_profile.numeric_stats}")
    
    assert salary_profile.semantic_type == "currency_amount", f"Expected currency_amount, got {salary_profile.semantic_type}"
    assert "currency" in salary_profile.patterns, "Currency pattern should be detected"
    assert salary_profile.is_numeric is True, "Salary should be numeric"


def test_team_column_classification():
    """Test that team columns are classified as categorical, not person_name."""
    df = pd.DataFrame({
        'team': ['ENG', 'FIN', 'ENG', 'HR']
    })
    profiles = profile_dataframe(df)
    team_profile = profiles['team']
    
    print(f"Team column semantic type: {team_profile.semantic_type}")
    print(f"Team column patterns: {team_profile.patterns}")
    print(f"Team column unique_ratio: {team_profile.unique_ratio}")
    
    # Team should be classified as categorical, not person_name
    assert team_profile.semantic_type in ["categorical", "department"], f"Expected categorical/department, got {team_profile.semantic_type}"
    assert team_profile.semantic_type != "person_name", "Team should not be classified as person_name"


def test_annual_salary_classification():
    """Test that Annual Salary is classified as currency_amount."""
    df = pd.DataFrame({
        'Annual Salary': ['95000', '105000', '89000', '120000']
    })
    profiles = profile_dataframe(df)
    annual_salary_profile = profiles['Annual Salary']
    
    print(f"Annual Salary semantic type: {annual_salary_profile.semantic_type}")
    
    assert annual_salary_profile.semantic_type == "currency_amount", f"Expected currency_amount, got {annual_salary_profile.semantic_type}"


if __name__ == '__main__':
    test_salary_column_classification()
    test_team_column_classification()
    test_annual_salary_classification()
    print("All salary classification tests passed!")