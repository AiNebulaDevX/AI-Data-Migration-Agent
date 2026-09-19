from __future__ import annotations

import json
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.config import settings


class Base(DeclarativeBase):
    pass


class MigrationORM(Base):
    __tablename__ = "migrations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="CREATED")
    demo_mode: Mapped[bool] = mapped_column(default=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    mappings_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SourceFileORM(Base):
    __tablename__ = "source_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[str] = mapped_column(String)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    columns_json: Mapped[str] = mapped_column(Text, default="[]")


class EscalationORM(Base):
    __tablename__ = "escalations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="OPEN")
    resolution_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CanonicalRecordORM(Base):
    __tablename__ = "canonical_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    employee_id: Mapped[str] = mapped_column(String, index=True)
    data_json: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String, default="PENDING")
    target_status: Mapped[str] = mapped_column(String, default="PENDING")
    record_hash: Mapped[str] = mapped_column(String, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class AuditEventORM(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String, default="agent")
    decision: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class ActivityORM(Base):
    __tablename__ = "activity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    message: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String, default="info")


class HumanOverrideORM(Base):
    __tablename__ = "human_overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String)
    value_json: Mapped[str] = mapped_column(Text)


class TargetStoreORM(Base):
    __tablename__ = "target_store"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, index=True)
    employee_id: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)


engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def add_activity(session: AsyncSession, migration_id: str, message: str, level: str = "info") -> None:
    session.add(
        ActivityORM(
            migration_id=migration_id,
            message=message,
            level=level,
            timestamp=datetime.utcnow(),
        )
    )


async def add_audit(
    session: AsyncSession,
    migration_id: str,
    action: str,
    *,
    record_id: Optional[str] = None,
    actor: str = "agent",
    decision: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    session.add(
        AuditEventORM(
            migration_id=migration_id,
            record_id=record_id,
            action=action,
            actor=actor,
            decision=decision,
            details_json=json.dumps(details or {}),
            timestamp=datetime.utcnow(),
        )
    )


async def get_open_escalations_count(session: AsyncSession, migration_id: str) -> int:
    result = await session.execute(
        select(EscalationORM).where(
            EscalationORM.migration_id == migration_id,
            EscalationORM.status == "OPEN",
        )
    )
    return len(result.scalars().all())
