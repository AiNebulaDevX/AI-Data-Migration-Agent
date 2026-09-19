from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.orchestrator import MigrationAgent, new_migration_id
from backend.config import settings
from backend.db.database import (
    ActivityORM,
    AuditEventORM,
    CanonicalRecordORM,
    EscalationORM,
    MigrationORM,
    SourceFileORM,
    TargetStoreORM,
    add_activity,
    get_session,
    init_db,
    SessionLocal,
)
from backend.models.schemas import HumanDecision, MigrationStats, MigrationStatus
from backend.target.client import TargetAPIClient

router = APIRouter()


class StartMigrationRequest(BaseModel):
    filenames: Optional[list[str]] = None
    demo_mode: bool = True
    uploaded_files: Optional[list[str]] = None


class ResolveEscalationRequest(BaseModel):
    decision: HumanDecision
    corrected_value: Optional[str] = None
    corrected_target_field: Optional[str] = None


async def _run_agent(migration_id: str, paths: list[Path], demo_mode: bool) -> None:
    async with SessionLocal() as session:
        agent = MigrationAgent(session, migration_id)
        try:
            await agent.start_with_files(paths, demo_mode=demo_mode)
        except Exception as exc:
            await add_activity(session, migration_id, f"Agent failed: {exc}", "error")
            mig = await session.get(MigrationORM, migration_id)
            if mig:
                mig.status = MigrationStatus.FAILED.value
            await session.commit()
            raise


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """Upload source files for migration."""
    upload_dir = settings.data_dir / "source"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    uploaded_filenames = []
    allowed = {".csv", ".xlsx", ".xls"}
    for file in files:
        # Generate unique filename to avoid conflicts
        file_extension = Path(file.filename or "").suffix.lower()
        if file_extension not in allowed:
            raise HTTPException(
                400,
                f"Unsupported file type: {file.filename}. Use CSV or Excel (.csv, .xlsx, .xls).",
            )
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = upload_dir / unique_filename
        
        # Save uploaded file
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        uploaded_filenames.append(unique_filename)
    
    return {
        "filenames": uploaded_filenames,
        "count": len(uploaded_filenames),
        "message": f"Successfully uploaded {len(uploaded_filenames)} files"
    }


@router.post("/migrations")
async def create_migration(body: StartMigrationRequest, background_tasks: BackgroundTasks):
    migration_id = new_migration_id()
    
    # Use uploaded files if provided, otherwise require filenames or use demo files
    if body.uploaded_files:
        filenames = body.uploaded_files
    elif body.filenames:
        filenames = body.filenames
    elif body.demo_mode:
        # Use default demo files for demo mode
        filenames = [
            "employees_hr.csv",
            "employees_legacy.csv",
            "employees_compensation.csv",
        ]
    else:
        raise HTTPException(400, "Either filenames or uploaded_files must be provided")
    
    paths = []
    for name in filenames:
        p = settings.data_dir / "source" / name
        if not p.exists():
            raise HTTPException(400, f"Missing source file: {name}")
        paths.append(p)

    async with SessionLocal() as session:
        session.add(
            MigrationORM(
                id=migration_id,
                status=MigrationStatus.CREATED.value,
                demo_mode=body.demo_mode,
            )
        )
        await session.commit()

    background_tasks.add_task(_run_agent, migration_id, paths, body.demo_mode)
    return {"migration_id": migration_id, "status": "STARTED", "files": filenames}





@router.get("/migrations/{migration_id}")
async def get_migration(migration_id: str, session: AsyncSession = Depends(get_session)):
    mig = await session.get(MigrationORM, migration_id)
    if not mig:
        raise HTTPException(404, "Migration not found")
    stats = await _compute_stats(session, migration_id)
    return {
        "id": mig.id,
        "status": mig.status,
        "demo_mode": mig.demo_mode,
        "stats": stats.model_dump(),
        "created_at": mig.created_at.isoformat(),
        "updated_at": mig.updated_at.isoformat(),
    }


async def _compute_stats(session: AsyncSession, migration_id: str) -> MigrationStats:
    files = await session.execute(select(SourceFileORM).where(SourceFileORM.migration_id == migration_id))
    file_rows = files.scalars().all()
    records = await session.execute(
        select(CanonicalRecordORM).where(CanonicalRecordORM.migration_id == migration_id)
    )
    recs = records.scalars().all()
    esc = await session.execute(
        select(EscalationORM).where(
            EscalationORM.migration_id == migration_id,
            EscalationORM.status == "OPEN",
        )
    )
    open_esc = len(esc.scalars().all())
    success = sum(1 for r in recs if r.target_status == "SUCCESS")
    failed = sum(1 for r in recs if r.target_status == "FAILED")
    valid = sum(1 for r in recs if r.validation_status == "VALID")
    total_rows = sum(f.row_count for f in file_rows)
    processed = len(recs) if recs else 0
    progress = 100.0 if success and not open_esc else min(95.0, (processed / max(total_rows, 1)) * 100)
    mig = await session.get(MigrationORM, migration_id)
    if mig and mig.status == "COMPLETED":
        progress = 100.0
    return MigrationStats(
        files_ingested=len(file_rows),
        total_source_rows=total_rows,
        records_processed=processed,
        records_cleaned=processed,
        auto_mapped_fields=len(json.loads(mig.mappings_json)) if mig and mig.mappings_json else 0,
        escalations_open=open_esc,
        target_success=success,
        target_failed=failed,
        progress_percent=round(progress, 1),
    )


@router.get("/migrations/{migration_id}/activity")
async def list_activity(migration_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ActivityORM)
        .where(ActivityORM.migration_id == migration_id)
        .order_by(ActivityORM.id.desc())
        .limit(100)
    )
    events = result.scalars().all()
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "message": e.message,
            "level": e.level,
        }
        for e in reversed(events)
    ]


@router.get("/migrations/{migration_id}/activity/stream")
async def stream_activity(migration_id: str, session: AsyncSession = Depends(get_session)):
    async def event_generator():
        last_id = 0
        while True:
            async with SessionLocal() as s:
                result = await s.execute(
                    select(ActivityORM)
                    .where(ActivityORM.migration_id == migration_id, ActivityORM.id > last_id)
                    .order_by(ActivityORM.id.asc())
                )
                rows = result.scalars().all()
                for row in rows:
                    last_id = row.id
                    payload = json.dumps(
                        {
                            "timestamp": row.timestamp.isoformat(),
                            "message": row.message,
                            "level": row.level,
                        }
                    )
                    yield f"data: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/migrations/{migration_id}/escalations")
async def list_escalations(migration_id: str):
    # Use a fresh session to ensure we get the latest committed data
    async with SessionLocal() as session:
        result = await session.execute(
            select(EscalationORM).where(EscalationORM.migration_id == migration_id).order_by(EscalationORM.id.asc())
        )
        out = []
        for row in result.scalars():
            payload = json.loads(row.payload_json)
            # Remove id and status from payload to avoid overwriting database fields
            payload.pop("id", None)
            payload.pop("status", None)
            out.append({"id": row.id, "status": row.status, **payload})
        return out


@router.post("/migrations/{migration_id}/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    migration_id: str,
    escalation_id: int,
    body: ResolveEscalationRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    agent = MigrationAgent(session, migration_id)
    await agent.load_mappings()
    await agent.resolve_escalation(
        escalation_id,
        body.decision,
        corrected_value=body.corrected_value,
        corrected_target_field=body.corrected_target_field,
    )
    await session.commit()

    async def cont():
        async with SessionLocal() as s:
            a = MigrationAgent(s, migration_id)
            await a.load_mappings()
            await a.continue_after_human()

    background_tasks.add_task(cont)
    return {"status": "RESOLVED", "continuing": True}


@router.get("/migrations/{migration_id}/records")
async def list_records(migration_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(CanonicalRecordORM).where(CanonicalRecordORM.migration_id == migration_id)
    )
    rows = []
    for r in result.scalars():
        rows.append(
            {
                "employee_id": r.employee_id,
                "data": json.loads(r.data_json),
                "validation_status": r.validation_status,
                "target_status": r.target_status,
                "retry_count": r.retry_count,
            }
        )
    return rows


@router.get("/migrations/{migration_id}/audit")
async def list_audit(migration_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AuditEventORM)
        .where(AuditEventORM.migration_id == migration_id)
        .order_by(AuditEventORM.id.asc())
    )
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "record_id": e.record_id,
            "action": e.action,
            "actor": e.actor,
            "decision": e.decision,
            "details": json.loads(e.details_json),
        }
        for e in result.scalars()
    ]


@router.get("/migrations/{migration_id}/files")
async def list_files(migration_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(SourceFileORM).where(SourceFileORM.migration_id == migration_id))
    return [
        {"filename": f.filename, "row_count": f.row_count, "columns": json.loads(f.columns_json)}
        for f in result.scalars()
    ]


@router.post("/migrations/{migration_id}/rollback")
async def rollback(migration_id: str, session: AsyncSession = Depends(get_session)):
    agent = MigrationAgent(session, migration_id)
    removed = await agent.rollback()
    await session.commit()
    return {"status": "ROLLED_BACK", "removed": removed}


@router.post("/reset-all")
async def reset_all(session: AsyncSession = Depends(get_session)):
    """Delete all migration data - for demo reset purposes."""
    await session.execute(text("DELETE FROM escalations"))
    await session.execute(text("DELETE FROM canonical_records"))
    await session.execute(text("DELETE FROM source_files"))
    await session.execute(text("DELETE FROM activity_events"))
    await session.execute(text("DELETE FROM audit_events"))
    await session.execute(text("DELETE FROM human_overrides"))
    await session.execute(text("DELETE FROM target_store"))
    await session.execute(text("DELETE FROM migrations"))
    await session.commit()
    return {"status": "RESET_COMPLETE"}


target_router = APIRouter(prefix="/target", tags=["target"])


@target_router.post("/employees")
async def target_employees(payload: dict[str, Any], session: AsyncSession = Depends(get_session)):
    """External-style target endpoint (also used internally via TargetAPIClient)."""
    migration_id = payload.get("_migration_id", "external")
    client = TargetAPIClient(session, migration_id, demo_mode=True)
    idem = payload.get("_idempotency_key", payload.get("employee_id", "unknown"))
    ok, msg = await client.push_employee(payload, idem, attempt=1)
    await session.commit()
    if not ok:
        return {"success": False, "error": msg}
    return {"success": True, "message": msg}


@target_router.get("/employees")
async def list_target_employees(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(TargetStoreORM).order_by(TargetStoreORM.id.desc()))
    return [json.loads(r.payload_json) for r in result.scalars()]
