import json
from datetime import datetime

from backend.models.schemas import AuditEvent


def test_audit_event_shape():
    evt = AuditEvent(
        migration_id="mig-1",
        record_id="EMP-101",
        action="FIELD_MAPPING",
        details={"confidence": 0.96},
        actor="agent",
        decision="AUTO_APPROVED",
    )
    data = evt.model_dump()
    assert data["action"] == "FIELD_MAPPING"
    assert "timestamp" in data
