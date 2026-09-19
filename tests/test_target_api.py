import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base, TargetStoreORM
from backend.target.client import TargetAPIClient


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_target_push_success(session):
    client = TargetAPIClient(session, "mig-test", demo_mode=False)
    payload = {
        "employee_id": "EMP-101",
        "first_name": "John",
        "last_name": "Smith",
        "email": "john@acme.com",
        "date_of_birth": "1990-05-15",
    }
    ok, msg = await client.push_employee(payload, "mig-test:hash1", attempt=1)
    assert ok is True
    await session.commit()


@pytest.mark.asyncio
async def test_target_push_retry_demo_failure(session):
    client = TargetAPIClient(session, "mig-test", demo_mode=True)
    payload = {
        "employee_id": "EMP-108",
        "first_name": "Demo",
        "last_name": "Fail",
        "email": "demo.fail@acme.com",
        "date_of_birth": "1990-06-01",
    }
    ok1, _ = await client.push_employee(payload, "mig-test:hash108", attempt=1)
    assert ok1 is False
    ok2, _ = await client.push_employee(payload, "mig-test:hash108", attempt=2)
    assert ok2 is True


@pytest.mark.asyncio
async def test_idempotency(session):
    client = TargetAPIClient(session, "mig-test", demo_mode=False)
    payload = {
        "employee_id": "EMP-101",
        "first_name": "John",
        "last_name": "Smith",
        "email": "john@acme.com",
        "date_of_birth": "1990-05-15",
    }
    ok1, _ = await client.push_employee(payload, "same-key", attempt=1)
    ok2, msg = await client.push_employee(payload, "same-key", attempt=1)
    assert ok1 and ok2
    assert "Idempotent" in msg


@pytest.mark.asyncio
async def test_rollback(session):
    client = TargetAPIClient(session, "mig-test", demo_mode=False)
    payload = {
        "employee_id": "EMP-101",
        "first_name": "John",
        "last_name": "Smith",
        "email": "john@acme.com",
        "date_of_birth": "1990-05-15",
    }
    await client.push_employee(payload, "key-rollback", attempt=1)
    await session.commit()
    removed = await client.rollback_migration()
    assert removed >= 1
