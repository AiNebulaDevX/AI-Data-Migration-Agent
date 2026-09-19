from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.llm_provider import get_llm_provider
from backend.cleaning.normalizers import (
    normalize_date,
    normalize_email,
    normalize_whitespace,
    split_full_name,
)
from backend.config import settings
from backend.db.database import (
    ActivityORM,
    AuditEventORM,
    CanonicalRecordORM,
    EscalationORM,
    HumanOverrideORM,
    MigrationORM,
    SourceFileORM,
    add_activity,
    add_audit,
    get_open_escalations_count,
)
from backend.ingestion.loader import load_source_file, profile_column_samples
from backend.mapping.confidence import rank_target_candidates, should_escalate_mapping
from backend.profiling.value_analyzer import profile_dataframe, ColumnProfile
from backend.models.schemas import (
    EscalationPayload,
    EscalationStatus,
    EscalationType,
    FieldMappingDecision,
    HumanDecision,
    MigrationStatus,
    TargetRecordStatus,
)
from backend.reconciliation.merge import merge_records, record_hash
from backend.target.client import TargetAPIClient
from backend.validation.employee_validator import load_target_schema, validate_employee_payload


class MigrationAgent:
    def __init__(self, session: AsyncSession, migration_id: str):
        self.session = session
        self.migration_id = migration_id
        self.target_schema = load_target_schema()
        self.mapping_decisions: dict[str, FieldMappingDecision] = {}
        self.pending_mapping_escalations: dict[str, int] = {}
        self.transformations: list[dict[str, Any]] = []
        self._resolved_escalations: set[str] = set()
        self._open_escalations: set[str] = set()

    async def _set_status(self, status: MigrationStatus) -> None:
        mig = await self.session.get(MigrationORM, self.migration_id)
        if mig:
            mig.status = status.value
            mig.updated_at = datetime.utcnow()

    async def _log(self, message: str, level: str = "info") -> None:
        await add_activity(self.session, self.migration_id, message, level)
        await self.session.commit()

    async def start_with_files(self, file_paths: list[Path], demo_mode: bool = True) -> None:
        mig = await self.session.get(MigrationORM, self.migration_id)
        if not mig:
            mig = MigrationORM(id=self.migration_id, status=MigrationStatus.UPLOAD.value, demo_mode=demo_mode)
            self.session.add(mig)
        else:
            mig.status = MigrationStatus.UPLOAD.value
            mig.demo_mode = demo_mode
        await self.session.commit()

        await self._set_status(MigrationStatus.INSPECT_FILES)
        await self._log(f"Starting migration {self.migration_id}")

        loaded = []
        for path in file_paths:
            await self._log(f"Reading {path.name}")
            sf = load_source_file(path)
            loaded.append(sf)
            await self._log(f"Detected {len(sf.columns)} columns in {path.name}")
            self.session.add(
                SourceFileORM(
                    migration_id=self.migration_id,
                    filename=sf.filename,
                    row_count=sf.row_count,
                    columns_json=json.dumps(sf.columns),
                )
            )
        await self.session.commit()

        await self._set_status(MigrationStatus.PROFILE_SCHEMAS)
        await self._log("Analyzing source schemas")

        await self._set_status(MigrationStatus.INFER_MAPPINGS)
        llm = await get_llm_provider()
        provider_name = type(llm).__name__
        await self._log(f"Inferring field mappings using {provider_name}")

        all_columns: dict[str, set[str]] = {}
        samples_by_col: dict[str, list[str]] = {}
        column_profiles: dict[str, dict[str, Any]] = {}  # Store column profiles
        
        for sf in loaded:
            # Profile the dataframe with value analysis
            profiles = profile_dataframe(sf.dataframe)
            column_profiles[sf.filename] = {col: asdict(profiles[col]) for col in profiles}
            
            for col in sf.columns:
                all_columns.setdefault(col, set()).add(sf.filename)
                key = f"{sf.filename}::{col}"
                samples_by_col[key] = profile_column_samples(sf.dataframe, col)

        for sf in loaded:
            llm_input_samples = {col: profile_column_samples(sf.dataframe, col) for col in sf.columns}
            llm_result = await llm.suggest_field_mappings(list(sf.columns), self.target_schema, llm_input_samples)
            llm_map = {m["source_column"]: m for m in llm_result.get("mappings", [])}

            for col in sf.columns:
                key = f"{sf.filename}::{col}"
                samples = samples_by_col[key]
                
                # Get column profile for this specific column
                col_profile = column_profiles.get(sf.filename, {}).get(col)
                profile_obj = ColumnProfile(**col_profile) if col_profile else None
                
                candidates, incompatible = rank_target_candidates(col, self.target_schema, samples, profile_obj)
                escalate, esc_reason, should_reject, decision_type = should_escalate_mapping(
                    col,
                    candidates,
                    incompatible,
                    settings.mapping_auto_threshold,
                    settings.mapping_ambiguity_gap,
                    profile_obj,
                )
                llm_hint = llm_map.get(col, {})
                decision = FieldMappingDecision(
                    source_column=col,
                    source_file=sf.filename,
                    candidates=candidates[:5],
                    confidence=candidates[0].confidence if candidates else 0.0,
                    reasons=candidates[0].reasons if candidates else [],
                )

                if decision_type == "REJECT":
                    # Reject semantically incompatible mappings
                    decision.target_field = None
                    decision.auto_applied = False
                    await add_audit(
                        self.session,
                        self.migration_id,
                        "FIELD_MAPPING",
                        details={
                            "source_file": sf.filename,
                            "source_field": col,
                            "target_field": None,
                            "confidence": decision.confidence,
                            "decision": "REJECTED",
                            "reason": esc_reason,
                            "semantic_type": profile_obj.semantic_type if profile_obj else "unknown",
                        },
                    )
                    await self._log(f"Rejected mapping for {col} in {sf.filename}: {esc_reason}")
                elif decision_type == "ESCALATE":
                    decision.escalated = True
                    await self._load_escalation_state()
                    esc_id = await self._create_escalation(
                        EscalationType.AMBIGUOUS_MAPPING,
                        record_id=None,
                        field=col,
                        source_value=", ".join(samples[:2]),
                        candidates=candidates[:3],
                        reason=esc_reason or llm_hint.get("reason", "Ambiguous mapping"),
                        confidence=decision.confidence,
                        recommended_action=f"Map to {candidates[0].target_field}" if candidates else "No viable mapping",
                        possible_consequences="Incorrect mapping may populate wrong target fields",
                        context={"source_file": sf.filename, "source_column": col, "semantic_type": profile_obj.semantic_type if profile_obj else "unknown"},
                    )
                    if esc_id is not None:
                        self.pending_mapping_escalations[key] = esc_id
                    await self._log(f"Escalating ambiguous mapping for {col} in {sf.filename}")
                elif decision_type == "AUTO_MAP":
                    decision.target_field = candidates[0].target_field
                    decision.auto_applied = True
                    await add_audit(
                        self.session,
                        self.migration_id,
                        "FIELD_MAPPING",
                        details={
                            "source_file": sf.filename,
                            "source_field": col,
                            "target_field": decision.target_field,
                            "confidence": decision.confidence,
                            "decision": "AUTO_APPROVED",
                            "reason": "; ".join(decision.reasons),
                            "semantic_type": profile_obj.semantic_type if profile_obj else "unknown",
                            "rejected_candidates": [inc["candidate"].target_field for inc in incompatible] if incompatible else [],
                        },
                    )
                    await self._log(f"Mapping {col} → {decision.target_field} ({decision.confidence:.0%})")
                self.mapping_decisions[key] = decision

        await self.session.commit()
        await self._persist_mappings()
        await self._set_status(MigrationStatus.WAITING_HUMAN)
        if self.pending_mapping_escalations:
            await self._log("Waiting for human decision on ambiguous mappings", "warning")
        else:
            await self.continue_after_human()

    def _escalation_key(self, etype: EscalationType, record_id: Optional[str], field: Optional[str], context: Optional[dict] = None) -> str:
        ctx = context or {}
        return f"{etype.value}:{record_id or ''}:{field or ''}:{ctx.get('source_file', '')}"

    async def _load_escalation_state(self) -> None:
        self._resolved_escalations.clear()
        self._open_escalations.clear()
        result = await self.session.execute(
            select(EscalationORM).where(EscalationORM.migration_id == self.migration_id)
        )
        for row in result.scalars():
            payload = json.loads(row.payload_json)
            key = self._escalation_key(
                EscalationType(payload["escalation_type"]),
                payload.get("record_id"),
                payload.get("field"),
                payload.get("context"),
            )
            if row.status == EscalationStatus.RESOLVED.value:
                self._resolved_escalations.add(key)
            elif row.status == EscalationStatus.OPEN.value:
                self._open_escalations.add(key)

    async def _create_escalation(self, etype: EscalationType, **kwargs: Any) -> Optional[int]:
        context = kwargs.get("context") or {}
        key = self._escalation_key(etype, kwargs.get("record_id"), kwargs.get("field"), context)
        if key in self._resolved_escalations or key in self._open_escalations:
            return None
        payload = EscalationPayload(
            migration_id=self.migration_id,
            escalation_type=etype,
            record_id=kwargs.get("record_id"),
            field=kwargs.get("field"),
            source_value=kwargs.get("source_value"),
            candidates=kwargs.get("candidates") or [],
            reason=kwargs.get("reason", ""),
            confidence=float(kwargs.get("confidence", 0)),
            recommended_action=kwargs.get("recommended_action", ""),
            possible_consequences=kwargs.get("possible_consequences", ""),
            context=kwargs.get("context") or {},
            source_values=kwargs.get("source_values") or {},
        )
        row = EscalationORM(
            migration_id=self.migration_id,
            payload_json=payload.model_dump_json(),
            status=EscalationStatus.OPEN.value,
        )
        self.session.add(row)
        await self.session.flush()
        await add_audit(
            self.session,
            self.migration_id,
            "ESCALATION_CREATED",
            record_id=payload.record_id,
            details={"type": etype.value, "field": payload.field, "reason": payload.reason},
        )
        self._open_escalations.add(key)
        return row.id

    async def resolve_escalation(
        self,
        escalation_id: int,
        decision: HumanDecision,
        corrected_value: Optional[str] = None,
        corrected_target_field: Optional[str] = None,
    ) -> None:
        row = await self.session.get(EscalationORM, escalation_id)
        if not row or row.status != EscalationStatus.OPEN.value:
            raise ValueError("Escalation not open")

        payload = EscalationPayload.model_validate_json(row.payload_json)
        resolution = {"decision": decision.value, "corrected_value": corrected_value, "corrected_target_field": corrected_target_field}

        if payload.escalation_type == EscalationType.AMBIGUOUS_MAPPING:
            key = f"{payload.context.get('source_file')}::{payload.field}"
            md = self.mapping_decisions.get(key)
            if md and decision == HumanDecision.APPROVE:
                md.target_field = md.candidates[0].target_field if md.candidates else corrected_target_field
                md.escalated = False
                md.auto_applied = False
            elif md and decision == HumanDecision.CORRECT and corrected_target_field:
                md.target_field = corrected_target_field
                md.escalated = False
                self.session.add(
                    HumanOverrideORM(
                        migration_id=self.migration_id,
                        key=f"mapping:{key}",
                        value_json=json.dumps({"target_field": corrected_target_field}),
                    )
                )
            elif md and decision == HumanDecision.REJECT:
                md.target_field = None
            self.pending_mapping_escalations.pop(key, None)

        elif payload.escalation_type in (
            EscalationType.VALIDATION_FAILURE,
            EscalationType.UNCLEANABLE_VALUE,
            EscalationType.CONFLICTING_RECORDS,
            EscalationType.SCHEMA_ERROR,
            EscalationType.MISSING_REQUIRED_FIELD,
            EscalationType.TRANSFORMATION_REQUIRED,
        ):
            eid = payload.record_id or payload.context.get("employee_id")
            if payload.escalation_type == EscalationType.CONFLICTING_RECORDS and decision == HumanDecision.APPROVE and eid:
                self.session.add(
                    HumanOverrideORM(
                        migration_id=self.migration_id,
                        key=f"conflict:{eid}:resolved",
                        value_json=json.dumps({"keep_existing": True}),
                    )
                )
            elif decision in (HumanDecision.APPROVE, HumanDecision.CORRECT) and eid:
                target_field = corrected_target_field or payload.field
                if target_field == "record":
                    target_field = "email"
                val = corrected_value
                if not val and payload.escalation_type == EscalationType.UNCLEANABLE_VALUE and payload.field == "date_of_birth":
                    val = "1995-02-01"
                elif not val and payload.escalation_type in (EscalationType.VALIDATION_FAILURE, EscalationType.SCHEMA_ERROR):
                    val = "valid.user@acme.com"
                if val and target_field:
                    self.session.add(
                        HumanOverrideORM(
                            migration_id=self.migration_id,
                            key=f"field:{eid}:{target_field}",
                            value_json=json.dumps({"value": val}),
                        )
                    )

        row.status = EscalationStatus.RESOLVED.value
        row.resolution_json = json.dumps(resolution)
        # Update payload status to match database status
        payload.status = EscalationStatus.RESOLVED
        row.payload_json = payload.model_dump_json()
        esc_key = self._escalation_key(
            payload.escalation_type,
            payload.record_id,
            payload.field,
            payload.context,
        )
        self._open_escalations.discard(esc_key)
        self._resolved_escalations.add(esc_key)
        await self._persist_mappings()
        await add_audit(
            self.session,
            self.migration_id,
            "ESCALATION_RESOLVED",
            record_id=payload.record_id,
            actor="human",
            decision=decision.value,
            details=resolution,
        )
        await self._log(f"Human {decision.value.lower()} escalation #{escalation_id}")
        await self.session.commit()

        open_count = await get_open_escalations_count(self.session, self.migration_id)
        if not self.pending_mapping_escalations and open_count == 0:
            await self.continue_after_human()

    async def _persist_mappings(self) -> None:
        mig = await self.session.get(MigrationORM, self.migration_id)
        if mig:
            mig.mappings_json = json.dumps({k: v.model_dump() for k, v in self.mapping_decisions.items()})
            await self.session.commit()

    async def load_mappings(self) -> None:
        mig = await self.session.get(MigrationORM, self.migration_id)
        if mig and mig.mappings_json:
            raw = json.loads(mig.mappings_json)
            self.mapping_decisions = {k: FieldMappingDecision(**v) for k, v in raw.items()}
        self.pending_mapping_escalations = {
            k: 1 for k, v in self.mapping_decisions.items() if v.escalated and not v.target_field
        }

    async def continue_after_human(self) -> None:
        await self.load_mappings()
        if self.pending_mapping_escalations:
            return
        open_count = await get_open_escalations_count(self.session, self.migration_id)
        if open_count > 0:
            await self._set_status(MigrationStatus.WAITING_HUMAN)
            return

        await self._set_status(MigrationStatus.APPLY_MAPPINGS)
        await self._log("Continuing migration after human resolution")
        await self._load_escalation_state()

        from sqlalchemy import delete

        await self.session.execute(
            delete(CanonicalRecordORM).where(CanonicalRecordORM.migration_id == self.migration_id)
        )

        mig = await self.session.get(MigrationORM, self.migration_id)
        demo_mode = mig.demo_mode if mig else True
        overrides = await self._load_overrides()
        conflict_resolved = {k.split(":")[1] for k in overrides if k.startswith("conflict:") and k.endswith(":resolved")}

        result = await self.session.execute(
            select(SourceFileORM).where(SourceFileORM.migration_id == self.migration_id)
        )
        source_files = result.scalars().all()
        paths = []
        for sf in source_files:
            p = settings.data_dir / "source" / sf.filename
            if p.exists():
                paths.append(load_source_file(p))

        canonical: dict[str, dict[str, Any]] = {}

        await self._set_status(MigrationStatus.CLEAN_DATA)
        for sf in paths:
            for _, row in sf.dataframe.iterrows():
                mapped: dict[str, Any] = {}
                employee_id = None
                for col in sf.columns:
                    key = f"{sf.filename}::{col}"
                    md = self.mapping_decisions.get(key)
                    if not md or not md.target_field:
                        continue
                    raw_val = str(row.get(col, "")).strip()
                    if not raw_val:
                        continue
                    target_field = md.target_field
                    val = raw_val
                    if target_field in ("first_name", "last_name", "department", "job_title"):
                        val, tr = normalize_whitespace(raw_val)
                        if tr:
                            tr.record_id = employee_id or "pending"
                            tr.field = target_field
                            self.transformations.append(tr.model_dump(mode="json"))
                    if target_field == "email":
                        val, tr = normalize_email(raw_val)
                        if tr:
                            tr.record_id = employee_id or "pending"
                            self.transformations.append(tr.model_dump(mode="json"))
                    if target_field in ("date_of_birth", "hire_date"):
                        override_key = f"field:{employee_id}:{target_field}" if employee_id else None
                        if override_key and override_key in overrides:
                            val = overrides[override_key]
                        else:
                            iso, tr, err = normalize_date(raw_val)
                            if err and "Ambiguous" in err:
                                await self._create_escalation(
                                    EscalationType.UNCLEANABLE_VALUE,
                                    record_id=employee_id,
                                    field=target_field,
                                    source_value=raw_val,
                                    reason=err,
                                    confidence=0.55,
                                    recommended_action="Confirm intended date format (MDY vs DMY)",
                                    possible_consequences="Wrong birth date in HRIS",
                                    context={"source_file": sf.filename, "employee_id": employee_id},
                                )
                                val = None
                            elif err:
                                val = None
                            elif tr:
                                tr.record_id = employee_id or "pending"
                                tr.field = target_field
                                self.transformations.append(tr.model_dump(mode="json"))
                                val = iso
                            else:
                                val = iso
                    if target_field == "full_name":
                        first, last, tr = split_full_name(val)
                        if tr:
                            self.transformations.append(tr.model_dump(mode="json"))
                        if first:
                            mapped["first_name"] = first
                        if last:
                            mapped["last_name"] = last
                        mapped["full_name"] = val
                        continue
                    mapped[target_field] = val
                    if target_field == "employee_id":
                        employee_id = val

                eid = mapped.get("employee_id")
                if not eid:
                    continue

                if eid in canonical:
                    canonical[eid], conflicts = merge_records(canonical[eid], mapped, sf.filename)
                    if conflicts and eid not in conflict_resolved:
                        await self._create_escalation(
                            EscalationType.CONFLICTING_RECORDS,
                            record_id=eid,
                            field="multiple",
                            source_value="; ".join(conflicts),
                            reason="Sources disagree on employee attributes",
                            confidence=0.5,
                            recommended_action="Pick authoritative value from HR export",
                            possible_consequences="Incorrect master data if wrong source wins",
                            context={"conflicts": conflicts},
                            source_values=mapped,
                        )
                else:
                    mapped["_sources"] = {k: sf.filename for k in mapped if not k.startswith("_")}
                    canonical[eid] = mapped

        await self._log(f"Detected {len(canonical)} unique employees after reconciliation")
        await self._set_status(MigrationStatus.VALIDATE)

        for eid, data in list(canonical.items()):
            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            for okey, oval in overrides.items():
                if okey.startswith(f"field:{eid}:"):
                    field = okey.split(":", 2)[2]
                    clean[field] = oval

            # Don't fabricate missing fields - only use what's available
            # if not clean.get("full_name") and clean.get("first_name"):
            #     clean["full_name"] = f"{clean.get('first_name','')} {clean.get('last_name','')}".strip()

            record, err = validate_employee_payload(clean)
            if err:
                err_lower = err.lower()
                field = "email" if "email" in err_lower else ("employee_id" if "employee_id" in err_lower else "record")
                source_val = str(clean.get(field, json.dumps(clean)))
                
                await self._create_escalation(
                    EscalationType.VALIDATION_FAILURE,
                    record_id=eid,
                    field=field,
                    source_value=source_val,
                    reason=err,
                    confidence=0.4,
                    recommended_action=f"Provide a valid value for {field}" if field != "record" else "Fix validation issues",
                    possible_consequences="Target API will reject record",
                    context={"validation_error": err, "field": field},
                )
                rec_row = CanonicalRecordORM(
                    migration_id=self.migration_id,
                    employee_id=eid,
                    data_json=json.dumps(clean),
                    validation_status="INVALID",
                    target_status=TargetRecordStatus.FAILED.value,
                    record_hash=record_hash(self.migration_id, eid, clean),
                )
                self.session.add(rec_row)
                continue

            rec_row = CanonicalRecordORM(
                migration_id=self.migration_id,
                employee_id=eid,
                data_json=json.dumps(record.model_dump(mode="json")),
                validation_status="VALID",
                target_status=TargetRecordStatus.PENDING.value,
                record_hash=record_hash(self.migration_id, eid, record.model_dump(mode="json")),
            )
            self.session.add(rec_row)

        await self.session.commit()

        open_count = await get_open_escalations_count(self.session, self.migration_id)
        if open_count > 0:
            await self._set_status(MigrationStatus.WAITING_HUMAN)
            await self._log(f"{open_count} records need human attention", "warning")
            return

        await self.push_valid_records(demo_mode)

    async def _load_overrides(self) -> dict[str, Any]:
        result = await self.session.execute(
            select(HumanOverrideORM).where(HumanOverrideORM.migration_id == self.migration_id)
        )
        out: dict[str, Any] = {}
        for row in result.scalars():
            val = json.loads(row.value_json)
            out[row.key] = val.get("value") if isinstance(val, dict) and "value" in val else val
        return out

    async def push_valid_records(self, demo_mode: bool) -> None:
        await self._set_status(MigrationStatus.PUSH_TARGET)
        client = TargetAPIClient(self.session, self.migration_id, demo_mode=demo_mode)
        result = await self.session.execute(
            select(CanonicalRecordORM).where(
                CanonicalRecordORM.migration_id == self.migration_id,
                CanonicalRecordORM.validation_status == "VALID",
            )
        )
        records = result.scalars().all()
        for rec in records:
            if rec.target_status == TargetRecordStatus.SUCCESS.value:
                continue
            payload = json.loads(rec.data_json)
            eid = payload["employee_id"]
            idem = f"{self.migration_id}:{rec.record_hash}"
            while rec.retry_count < settings.target_max_retries:
                attempt = rec.retry_count + 1
                rec.target_status = TargetRecordStatus.RETRYING.value if attempt > 1 else TargetRecordStatus.PENDING.value
                await self._log(f"Pushing {eid} to target (attempt {attempt})")
                ok, msg = await client.push_employee(payload, idem, attempt)
                if ok:
                    rec.target_status = TargetRecordStatus.SUCCESS.value
                    await self._log(f"Successfully pushed {eid}" + (" on retry" if attempt > 1 else ""))
                    break
                rec.retry_count = attempt
                if attempt >= settings.target_max_retries:
                    rec.target_status = TargetRecordStatus.FAILED.value
                    await self._create_escalation(
                        EscalationType.TARGET_PUSH_FAILURE,
                        record_id=eid,
                        field="target_api",
                        source_value=msg,
                        reason=msg,
                        confidence=0.3,
                        recommended_action="Retry after fixing data or rollback migration",
                        possible_consequences="Employee missing in target system",
                        context={"attempts": attempt},
                    )
                    await self._log(f"Target push failed for {eid}: {msg}", "error")
                else:
                    await self._log(f"Retrying {eid} after failure: {msg}", "warning")

        await self.session.commit()
        open_count = await get_open_escalations_count(self.session, self.migration_id)
        failed = sum(
            1
            for r in records
            if r.target_status in (TargetRecordStatus.FAILED.value, TargetRecordStatus.RETRYING.value)
        )
        if open_count:
            await self._set_status(MigrationStatus.WAITING_HUMAN)
        else:
            await self._set_status(MigrationStatus.COMPLETED)
            await self._log("Migration completed")

    async def rollback(self) -> int:
        client = TargetAPIClient(self.session, self.migration_id)
        removed = await client.rollback_migration()
        await self._set_status(MigrationStatus.ROLLED_BACK)
        await self._log(f"Rollback removed {removed} target records", "warning")
        return removed


def new_migration_id() -> str:
    return f"mig-{uuid.uuid4().hex[:12]}"
