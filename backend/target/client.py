from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.database import TargetStoreORM, add_audit
from backend.models.schemas import TargetRecordStatus


class TargetAPIClient:
    """Mock target system with deterministic demo failures and idempotency."""

    def __init__(self, session: AsyncSession, migration_id: str, demo_mode: bool = True):
        self.session = session
        self.migration_id = migration_id
        self.demo_mode = demo_mode
        self._fail_attempts: dict[str, int] = {}

    async def push_employee(self, payload: dict[str, Any], idempotency_key: str, attempt: int) -> tuple[bool, str]:
        employee_id = payload.get("employee_id", "")

        existing = await self.session.execute(
            select(TargetStoreORM).where(TargetStoreORM.idempotency_key == idempotency_key)
        )
        if existing.scalar_one_or_none():
            return True, "Idempotent skip — already applied"

        if self.demo_mode and employee_id == "EMP-108" and attempt < 2:
            await add_audit(
                self.session,
                self.migration_id,
                "TARGET_PUSH",
                record_id=employee_id,
                details={"status": "FAILED", "attempt": attempt, "error": "Simulated transient outage"},
            )
            return False, "Simulated transient target API failure (demo)"

        if employee_id == "EMP-107" and ("not-an-email" in str(payload.get("email", "")) or not payload.get("email")):
            return False, "Invalid employee data rejected by target policy"

        self.session.add(
            TargetStoreORM(
                migration_id=self.migration_id,
                employee_id=employee_id,
                payload_json=json.dumps(payload),
                idempotency_key=idempotency_key,
            )
        )
        await add_audit(
            self.session,
            self.migration_id,
            "TARGET_PUSH",
            record_id=employee_id,
            details={"status": "SUCCESS", "attempt": attempt},
        )
        return True, "Accepted"

    async def rollback_migration(self) -> int:
        result = await self.session.execute(
            delete(TargetStoreORM).where(TargetStoreORM.migration_id == self.migration_id)
        )
        await add_audit(
            self.session,
            self.migration_id,
            "TARGET_ROLLBACK",
            actor="agent",
            details={"removed": result.rowcount or 0},
        )
        return result.rowcount or 0
