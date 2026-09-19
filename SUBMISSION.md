# Submission — Migration Agent Prototype

## Approach

I scoped a **single-entity employee migration** that fully demonstrates the product concept: an agent that runs autonomously on safe work and pauses only when business risk exceeds a defensible confidence threshold. The implementation prioritizes explainability and demo reliability over breadth.

## Architecture

**React control-center UI** ↔ **FastAPI agent backend** ↔ **SQLite** (migrations, escalations, audit, target store). The agent orchestrator (`backend/agent/orchestrator.py`) drives an explicit state machine. **Ollama (llama3.2)** provides semantic mapping suggestions behind a `LLMProvider` interface; a **deterministic confidence engine** (`mapping/confidence.py`) makes all autonomy decisions. Pandas ingests CSV/XLSX; Pydantic validates against `data/target-schema/employees.yaml`.

## How the agent works autonomously

- Maps known HR/CRM column synonyms automatically (≥94% confidence)
- Normalizes whitespace, email casing, and unambiguous dates
- Deduplicates and merges records across three source files by `employee_id`
- Validates records and pushes to a mock target API with idempotency and retry
- Logs every decision to a structured audit trail

## What the agent escalates

1. **Ambiguous mapping** — legacy `Name` → `full_name` vs `first_name`
2. **Uncleanable value** — `01/02/1995` (MDY/DMY ambiguity)
3. **Conflicting records** — EMP-102 department differs across HR and CRM
4. **Validation failure** — EMP-107 invalid email
5. **Target push failure** — after retry exhaustion or permanent rejection

## Why this escalation boundary

**Auto-approve synonyms and formatting** because errors are recoverable and rules are industry-standard. **Escalate ambiguous names and dates** because silent wrong choices corrupt HR master data. **Escalate conflicts** because no algorithm knows whether HR or CRM is authoritative. Threshold: 85% confidence + 12% gap between top candidates — tuned so obvious mappings pass while near-ties pause.

## Human supervision without micromanagement

The consultant sees a dashboard answering: *What is the agent doing? Does it need me?* Only 1–4 escalations appear per demo run (not per record). Each card includes source value, candidate mappings with confidence reasons, recommended action, and Approve/Correct/Reject. One decision resumes the full pipeline — no manual restart.

## AI vs deterministic logic

AI suggests mappings and explains uncertainty. Deterministic code enforces schema validation, confidence thresholds, idempotent writes, retry limits, rollback, and audit. If Ollama is unavailable, the same confidence engine runs via an explicit fallback — never hidden as AI.

## What I would build next

Mapping memory across migrations, multi-entity support, per-field conflict picker in UI, file upload, Postgres + background workers, and RBAC for enterprise rollout.
