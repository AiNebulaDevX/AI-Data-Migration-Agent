# AI Data Migration Agent - Project Summary

## Approach

I built a single-entity employee migration system that demonstrates an AI agent's autonomous decision-making capabilities with confidence-based human escalation. The implementation prioritizes operational reliability and explainability over feature breadth, focusing on the core challenge: **when should an AI act autonomously versus when should it escalate to a human?**

## Architecture

**React control-center UI** ↔ **FastAPI agent backend** ↔ **SQLite** (migrations, escalations, audit, target store). The agent orchestrator drives an explicit state machine through the migration pipeline. **Ollama (llama3.2)** provides semantic mapping suggestions via an LLM provider interface, while a **deterministic confidence engine** makes all autonomy decisions. Pandas ingests CSV/XLSX files, Pydantic validates against the target schema, and a mock target API simulates production integration.

## Autonomy vs Escalation Boundary

The agent autonomously handles:
- **Known column synonyms** (empId → employee_id, givenName → first_name) at ≥94% confidence
- **Safe data formatting** (whitespace trim, email lowercasing, unambiguous date parsing)
- **High-confidence mappings** where top candidate ≥85% and gap to second candidate ≥12%
- **Duplicate detection** and record reconciliation across source files
- **Target push retries** (up to 3 attempts with idempotency)

The agent escalates when:
- **Ambiguous mapping** (e.g., legacy "Name" column could map to full_name or first_name)
- **Uncleanable values** (e.g., "01/02/1995" has MDY vs DMY ambiguity)
- **Conflicting records** (same employee has different values across source files)
- **Validation failures** (e.g., invalid email format that cannot be auto-corrected)
- **Target push failures** (after retry exhaustion or permanent rejection)

**Rationale for thresholds:** 85% auto-threshold + 12% gap prevents guessing when fields score similarly. Synonym matches bypass the threshold entirely as they represent clear semantic equivalence. Ambiguous dates and cross-source conflicts represent business-risk events where wrong choices corrupt master data — a consultant must decide once, then the agent continues without restarting the migration.

## Human-in-the-Loop Design

The consultant sees a dashboard answering: *What is the agent doing? Does it need me?* Only 1–4 escalations appear per migration (not per record). Each escalation card includes source values, candidate mappings with confidence scores and reasoning, recommended actions, and Approve/Correct/Reject options. One human decision resumes the full pipeline — no manual restart required.

## AI vs Deterministic Split

AI provides semantic mapping suggestions and explains uncertainty in natural language. Deterministic code enforces schema validation, confidence thresholds, idempotent writes, retry limits, rollback, and comprehensive audit logging. If Ollama is unavailable, the same confidence engine runs via an explicit fallback — never hidden as AI.

## What Was Built

- **Multi-file ingestion**: CSV/XLSX loading with automatic schema profiling
- **Intelligent mapping**: AI-assisted field mapping with confidence scoring
- **Data cleaning**: Normalization of dates, emails, whitespace, and casing
- **Reconciliation**: Duplicate detection and record merging across sources
- **Validation**: Pydantic schema validation against target requirements
- **Mock target API**: Stub integration with retry, rollback, and per-record status
- **Escalation system**: Confidence-based human intervention for ambiguous cases
- **Web UI**: React dashboard with live activity monitoring and escalation resolution
- **Audit trail**: Complete record of all agent and human decisions

## What I'd Build Next

- **Multi-entity migrations**: Extend support for departments, locations, and other entity types
- **File upload in UI**: Add S3 integration for direct file uploads instead of bundled demo files
- **Mapping memory**: Learn and remember successful mappings across client engagements
- **Per-field conflict picker**: Richer UI allowing consultants to choose winning source per field
- **Production deployment**: PostgreSQL database, background job queue, and monitoring
- **Role-based access**: Different permissions for consultants vs admins
- **Advanced conflict resolution**: Smart merging strategies for complex data conflicts

## Live Demo

https://ai-data-migration-agent.vercel.app/

## Source Code

https://github.com/AiNebulaDevX/AI-Data-Migration-Agent