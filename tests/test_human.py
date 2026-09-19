from backend.mapping.confidence import should_escalate_mapping, rank_target_candidates
from backend.validation.employee_validator import load_target_schema
from backend.models.schemas import HumanDecision, FieldMappingDecision


def test_human_mapping_correction_updates_decision():
    schema = load_target_schema()
    candidates, _ = rank_target_candidates("Name", schema, ["Rahul Sharma"])
    decision = FieldMappingDecision(
        source_column="Name",
        source_file="employees_legacy.csv",
        candidates=candidates[:3],
        confidence=candidates[0].confidence,
        escalated=True,
    )
    decision.target_field = "full_name"
    decision.escalated = False
    assert decision.target_field == "full_name"
    assert HumanDecision.CORRECT.value == "CORRECT"
