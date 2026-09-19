import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.agent.orchestrator import MigrationAgent, new_migration_id
from backend.config import settings
from backend.db.database import Base, EscalationORM, MigrationORM
from backend.models.schemas import HumanDecision


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_agent_pauses_on_ambiguous_mapping_then_resumes(session):
    mid = new_migration_id()
    paths = [
        settings.data_dir / "source" / "employees_hr.csv",
        settings.data_dir / "source" / "employees_crm.xlsx",
        settings.data_dir / "source" / "employees_legacy.csv",
    ]
    agent = MigrationAgent(session, mid)
    await agent.start_with_files(paths, demo_mode=True)

    mig = await session.get(MigrationORM, mid)
    assert mig.status == "WAITING_HUMAN"

    open_esc = (
        await session.execute(
            select(EscalationORM).where(
                EscalationORM.migration_id == mid,
                EscalationORM.status == "OPEN",
            )
        )
    ).scalars().all()
    types = {json.loads(e.payload_json)["escalation_type"] for e in open_esc}
    assert "AMBIGUOUS_MAPPING" in types

    name_esc = next(
        e for e in open_esc if json.loads(e.payload_json).get("field") == "Name"
    )
    await agent.resolve_escalation(name_esc.id, HumanDecision.APPROVE)
    await session.commit()
    await agent.continue_after_human()
    await session.commit()

    mig = await session.get(MigrationORM, mid)
    assert mig.status in ("WAITING_HUMAN", "COMPLETED", "PUSH_TARGET")
