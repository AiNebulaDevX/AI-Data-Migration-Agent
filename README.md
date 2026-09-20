# Migration Agent — AI-Assisted Client Data Migration

A production-minded prototype for **autonomous employee data migration** with confidence-based escalation and human-in-the-loop supervision. Built for a Forward Deployed Engineer take-home: multi-file ingestion, schema inference, safe cleaning, reconciliation, mock target API integration, and a full audit trail.

## 🚀 Quick Deploy to Railway

This project is configured for one-click deployment to Railway. See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.

**Quick Start:**
1. Push this repository to GitHub
2. Create a new Railway project from the repo
3. Add PostgreSQL database service
4. Configure environment variables (AI provider, API keys)
5. Deploy both backend and frontend services

## Problem

Clients migrating HR/CRM systems provide multiple exports of the same entity (employees) with inconsistent column names, date formats, duplicates, missing fields, and conflicting values. This agent:

1. Ingests multiple source files
2. Infers source → target field mappings
3. Cleans data when safe
4. Validates against a target schema
5. Reconciles files into one canonical dataset
6. Pushes to a mock target API
7. Escalates only when genuinely ambiguous or unsafe
8. Lets a non-technical consultant supervise via a web UI

## Architecture

```
React + TypeScript UI  ←→  FastAPI Backend  ←→  SQLite
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   Ingestion (pandas)   AI Layer (Ollama)    Deterministic Engine
         │                    │                    │
         └────────────────────┴────────────────────┘
                              ▼
              Mapping · Cleaning · Validation · Reconciliation
                              ▼
                     Mock Target REST API
```

### AI vs deterministic responsibilities

| Layer | Responsibilities |
|-------|------------------|
| **AI (Ollama / llama3.2)** | Semantic mapping hints, rationale for uncertain columns, structured JSON suggestions |
| **Deterministic** | Synonym matching, confidence scoring, threshold enforcement, Pydantic validation, date/email normalization, deduplication, idempotency, retries, rollback, audit logging, escalation gating |

If Ollama is unavailable or the model is not installed, the system falls back to `DeterministicFallbackLLMProvider` — the same confidence engine, clearly labeled (not fake AI).

## Agent workflow

```
UPLOAD → INSPECT → PROFILE → INFER MAPPINGS → [HIGH CONFIDENCE? → AUTO]
                                                      ↓ NO
                                               ESCALATE → WAIT FOR HUMAN
                                                      ↓
                              APPROVE / CORRECT / REJECT → CONTINUE
                                                      ↓
                    CLEAN → VALIDATE → RECONCILE → PUSH TARGET → COMPLETE
```

State machine: `backend/agent/orchestrator.py` (`MigrationStatus` enum)

## Autonomy boundary

### Agent handles autonomously

- **Known column synonyms** (`empId` → `employee_id`, `givenName` → `first_name`, `dob` → `date_of_birth`) — confidence ≥ 94% when synonym dictionary matches
- **Safe formatting**: whitespace trim, email lowercasing, unambiguous date parsing (ISO, `DD-MM-YYYY` where day > 12)
- **Duplicate detection** across files by `employee_id`
- **High-confidence mappings** where top candidate ≥ 85% and gap to second candidate ≥ 12%
- **Target push retries** (up to 3 attempts; demo simulates transient failure for `EMP-108`)

### Agent escalates

| Case | Example in demo | Why |
|------|-----------------|-----|
| **Ambiguous mapping** | Legacy column `Name` → `full_name` vs `first_name` | Multi-word values fit both targets; wrong choice corrupts employee names in HRIS |
| **Uncleanable value** | `01/02/1995` for EMP-102 | MDY vs DMY ambiguity — guessing could swap birth month/day |
| **Conflicting records** | EMP-102 department: `Sales` vs `Enterprise Sales` | Sources disagree; agent cannot know which system is authoritative |
| **Validation failure** | EMP-107 email `not-an-email` | Pydantic rejects invalid email; no safe auto-fix |
| **Target push failure** | After retry exhaustion | Persistent API rejection needs human decision or rollback |

**Why these thresholds?**  
85% auto threshold + 12% gap prevents the agent from guessing when two fields score similarly. Synonym matches bypass guessing entirely. Ambiguous dates and cross-source conflicts are business-risk events — a consultant must decide once, then the agent continues without restarting the migration.

## Tech stack

- **Frontend**: React 18, TypeScript, Vite
- **Backend**: Python 3.12, FastAPI, SQLAlchemy, Pydantic
- **Data**: pandas, openpyxl, PyYAML
- **AI**: Ollama + llama3.2 (optional; fallback included)
- **Persistence**: SQLite
- **Realtime**: Server-Sent Events (activity stream) + polling

## Project structure

```
├── frontend/              # React control-center UI
├── backend/
│   ├── agent/             # Orchestrator + LLM provider abstraction
│   ├── ingestion/         # CSV/XLSX loading
│   ├── mapping/           # Confidence engine
│   ├── cleaning/          # Normalizers
│   ├── validation/        # Pydantic + target schema
│   ├── reconciliation/    # Merge + dedupe
│   ├── target/            # Mock target API client
│   ├── db/                # SQLite models
│   └── api/               # REST + SSE routes
├── data/
│   ├── source/            # Demo HR, CRM, legacy files
│   └── target-schema/     # employees.yaml
├── tests/
├── README.md
└── SUBMISSION.md
```

## Setup

### Prerequisites

- Python 3.12+
- Node.js 18+
- (Optional) [Ollama](https://ollama.com) with `llama3.2`

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ..
uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — API defaults to http://localhost:8000/api

### Ollama (optional)

```bash
ollama pull llama3.2
ollama serve
```

Configure via env: `MIGRATION_OLLAMA_MODEL=llama3.2`, `MIGRATION_OLLAMA_BASE_URL=http://localhost:11434`

Without Ollama, the deterministic fallback runs automatically.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Demo walkthrough (~3 minutes)

1. **Start** — Click **Start demo migration** on the dashboard.
2. **Watch agent activity** — Files ingested, columns detected, mappings applied autonomously.
3. **Escalation appears** — Legacy `Name` column: ambiguous `full_name` vs `first_name`.
4. **Resolve** — Go to **Escalations**, click **Approve** (recommended: map to `full_name`).
5. **Agent continues** — Resolves date ambiguity (EMP-102), department conflict, invalid email (EMP-107).
6. **Fix remaining escalations**:
   - EMP-102 date → **Correct** with `1995-02-01`
   - EMP-102 conflict → **Approve** (keep HR value)
   - EMP-107 email → **Correct** with `valid.user@acme.com` or reject
7. **Records tab** — See `SUCCESS`, `RETRYING` (EMP-108 demo retry), `FAILED` states.
8. **Audit log** — Every mapping, transformation, escalation, and API push.
9. **Rollback** — Removes all records pushed for this migration from the mock target.

## Deployment

### Railway Deployment (Recommended)

This project is pre-configured for Railway deployment with:
- Automatic Git-based CI/CD
- Railway PostgreSQL database
- Multiple AI provider options (OpenAI, Anthropic, Ollama, or deterministic fallback)
- Separate backend and frontend services

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete deployment instructions.

### Local Development

Follow the setup instructions below for local development.

## Screenshots

### Dashboard
![Dashboard](screenshots/dashboard.png)

### Escalations Interface
![Escalations](screenshots/escalations.png)

### Agent Activity
![Agent Activity](screenshots/activity.png)

### Records View
![Records](screenshots/records.png)

### Audit Log
![Audit Log](screenshots/audit.png)

## Target API

- `POST /api/target/employees` — accepts transformed employee records
- Idempotency via `{migration_id}:{record_hash}` keys
- Demo behaviors:
  - `EMP-108`: transient failure on attempt 1, success on retry
  - `EMP-107`: permanent rejection (invalid policy)
- Rollback: `POST /api/migrations/{id}/rollback`

## Idempotency

- Stable keys: `migration_id + SHA256(record payload)`
- Re-pushing the same record returns success without duplicate writes
- Human overrides stored in `human_overrides` and applied on resume — never overwritten by AI

## Acceptance criteria checklist

| Requirement | Implementation | UI | Test | Demo step |
|-------------|----------------|-----|------|-----------|
| Multi-file ingestion | `ingestion/loader.py`, `orchestrator.py` | Files tab | — | Start migration |
| Same entity across files | Reconciliation by `employee_id` | Records tab | `test_reconciliation.py` | Records list |
| Different column names | Demo CSV/XLSX/legacy | Files tab | `test_mapping.py` | Files tab |
| Automatic schema mapping | `mapping/confidence.py` + LLM | Activity feed | `test_mapping.py` | Activity stream |
| Automatic cleanup | `cleaning/normalizers.py` | Audit log | `test_cleaning.py` | Audit log |
| Duplicate handling | `reconciliation/merge.py` | Activity feed | `test_reconciliation.py` | Activity |
| Validation | `validation/employee_validator.py` | Records tab | `test_validation.py` | Records |
| Confidence-based autonomy | `mapping/confidence.py` | Escalation cards | `test_mapping.py` | Dashboard |
| Ambiguous mapping escalation | `Name` column rule | Escalations | `test_mapping.py` | Escalations |
| Validation failure escalation | EMP-107 | Escalations | `test_validation.py` | Escalations |
| Uncleanable value escalation | EMP-102 date | Escalations | `test_cleaning.py` | Escalations |
| Conflicting records | EMP-102 department | Escalations | `test_reconciliation.py` | Escalations |
| Human approve/correct/reject | `resolve_escalation` | Escalation buttons | `test_human.py` | Escalations |
| Agent resumes after human | `continue_after_human` | Status changes | — | After approve |
| Live agent activity | SSE + polling | Agent Activity | — | Activity tab |
| Escalation queue | `EscalationORM` | Escalations tab | — | Escalations |
| Mock target API | `target/client.py`, routes | Records tab | `test_target_api.py` | Records |
| Per-record success/failure | `CanonicalRecordORM.target_status` | Records tab | `test_target_api.py` | Records |
| Retry | `push_valid_records` loop | Records + audit | `test_target_api.py` | EMP-108 |
| Rollback | `rollback()` | Header button | `test_target_api.py` | Rollback |
| Audit trail | `add_audit()` | Audit Log tab | `test_audit.py` | Audit tab |
| AI + deterministic split | `llm_provider.py` + confidence | README | — | Architecture |
| Open-source AI model | Ollama integration | README | — | Optional Ollama |
| Tests | `tests/` | — | `pytest` | CI |
| Screenshots | `screenshots/` directory | README | — | Screenshots section |
