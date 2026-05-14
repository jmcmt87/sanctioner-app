# CLAUDE.md — Sanctions Screening Assistant

## Project Overview

AI-powered compliance research tool for dual-jurisdiction sanctions analysis (US OFAC + EU Reg. 833/2014 + Germany BaFin/Bundesbank). Enables compliance analysts at European financial institutions to query sanctions data using natural language.

**This is a research assistant, NOT a real-time transaction screening system.** It sits alongside the analyst during alert investigations, providing sourced answers about sanctioned entities, regulatory interpretation, and enforcement precedents.

**Key differentiator:** Every response must include source citations and data vintage timestamps. An unsourced answer is worse than no answer in this domain.

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React + TypeScript | Split-view: chat panel, citations sidebar, agent trace panel |
| API | FastAPI + Pydantic | Async + WebSocket for streaming. OpenAPI docs auto-generated |
| Agent Orchestration | LangGraph + LangChain | LangGraph for state machine routing. LangChain for SQL chains, retrievers, output parsers |
| LLM | Mistral (swappable) | Dev: Mistral API. PoC: Ollama + Ministral 14B. Prod: vLLM + Mistral Large 3 |
| Database | PostgreSQL 16 + pgvector | Single DB: structured entity tables + vector embeddings + metadata |
| Embeddings | sentence-transformers (self-hosted) | Zero external API calls. Model TBD (likely BAAI/bge-m3 for multilingual) |
| Data Lake | AWS S3 | Raw document storage. SSE-KMS encrypted. Source of truth for ingestion |
| Observability | LangSmith + Prometheus | Agent decision tracing, query routing visibility |
| Python Tooling | uv | Package management, virtual environments, script running. Single tool replaces pip, pip-tools, venv, and virtualenv |
| Infrastructure | AWS (EC2, RDS, S3, CloudFront, ALB) | VPC isolation, private subnets, KMS encryption |

## LLM Configuration

The LLM is swappable via three environment variables. **Never hardcode model references.**

```
LLM_BASE_URL=       # e.g., https://api.mistral.ai/v1 or http://localhost:11434/v1
LLM_MODEL_NAME=     # e.g., mistral-large-latest or ministral-14b
LLM_API_KEY=        # API key (empty string for local Ollama)
```

All LLM calls go through a single abstraction layer so swapping providers requires zero code changes.

## Project Structure

```
sanctions-screening-assistant/
├── CLAUDE.md
├── README.md
├── task_plan.md
├── .python-version              # Pin Python version for uv (e.g., "3.13")
├── docs/
│   └── founding_document.md
│
├── backend/
│   ├── pyproject.toml            # uv manages deps here
│   ├── uv.lock                   # Committed to git — reproducible installs
│   ├── alembic/                  # DB migrations
│   │   └── versions/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry point
│   │   ├── config.py             # Settings via pydantic-settings (env vars)
│   │   ├── dependencies.py       # FastAPI dependency injection
│   │   │
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── query.py      # POST /api/query — main chat endpoint
│   │   │   │   ├── entity.py     # GET /api/entity-search — direct entity lookup
│   │   │   │   └── stream.py     # WebSocket /api/stream — streaming responses
│   │   │   └── schemas/          # Pydantic request/response models
│   │   │
│   │   ├── agent/
│   │   │   ├── graph.py          # LangGraph state machine definition
│   │   │   ├── nodes/
│   │   │   │   ├── preprocess.py # preprocess_query node (normalize, extract entities, decompose)
│   │   │   │   ├── classify.py   # classify_query node (intent routing)
│   │   │   │   ├── sql_lookup.py # execute_sql node (entity + vessel lookups)
│   │   │   │   ├── retrieve.py   # retrieve_docs node (RAG)
│   │   │   │   ├── synthesize.py # synthesize node (merge results + citations)
│   │   │   │   └── format_response.py # format_response node (translate, enforce format, add vintage)
│   │   │   ├── prompts/          # All LLM prompt templates (Jinja2 or plain text)
│   │   │   └── state.py          # LangGraph state schema
│   │   │
│   │   ├── db/
│   │   │   ├── models.py         # SQLAlchemy ORM models
│   │   │   ├── session.py        # Async session factory
│   │   │   └── repositories/     # Data access layer (one per domain)
│   │   │
│   │   ├── retrieval/
│   │   │   ├── embeddings.py     # Embedding model wrapper
│   │   │   ├── vector_store.py   # pgvector search operations
│   │   │   ├── bm25.py           # PostgreSQL full-text search wrapper
│   │   │   ├── ensemble.py       # Hybrid retriever (BM25 + semantic + RRF)
│   │   │   └── reranker.py       # Cross-encoder reranker (optional, added if evals warrant)
│   │   │
│   │   └── llm/
│   │       └── client.py         # LLM client abstraction (wraps Mistral/Ollama/vLLM)
│   │
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_agent/
│   │   ├── test_api/
│   │   ├── test_retrieval/
│   │   └── eval/                 # Retrieval quality evaluation harness
│   │       ├── eval_queries.json # Domain expert validated query set
│   │       └── run_eval.py
│   │
│   ├── Dockerfile
│   └── docker-compose.yml        # Local dev: postgres + app
│
├── ingestion/
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── runner.py             # Main pipeline orchestrator
│   │   ├── sources/
│   │   │   ├── ofac_sdn.py       # OFAC SDN CSV parser
│   │   │   ├── ofac_nonsdn.py    # OFAC Non-SDN list parser
│   │   │   ├── ofac_vessels.py   # OFAC vessel designations parser
│   │   │   ├── eu_sanctions.py   # EU Consolidated List XML parser
│   │   │   ├── enforcement.py    # Enforcement action PDF ingestion
│   │   │   ├── regulations.py    # EU regulation text ingestion (structure-aware)
│   │   │   └── guidance.py       # FAQ/guidance document ingestion
│   │   ├── chunking/
│   │   │   ├── text_chunker.py   # RecursiveCharacterTextSplitter wrapper
│   │   │   └── regulation_chunker.py  # Structure-aware chunker for legal texts
│   │   ├── embeddings.py         # Batch embedding generation
│   │   └── loaders.py            # S3 download + local file helpers
│   │
│   ├── scripts/
│   │   ├── ingest_all.py         # Full re-ingestion
│   │   ├── ingest_incremental.py # Delta updates for sanctions lists
│   │   └── check_freshness.py    # Data vintage reporting
│   │
│   ├── pyproject.toml            # uv manages deps here
│   ├── uv.lock                   # Committed to git — reproducible installs
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── CitationSidebar.tsx
│   │   │   ├── AgentTracePanel.tsx
│   │   │   └── EntityCard.tsx
│   │   ├── hooks/
│   │   ├── services/              # API client
│   │   └── types/
│   ├── package.json
│   └── Dockerfile
│
└── infra/
    ├── terraform/                 # AWS infrastructure (VPC, EC2, RDS, S3, ALB, CloudFront)
    └── docker-compose.prod.yml
```

## Agent Pipeline Architecture

Six-node LangGraph pipeline. The two wrapper nodes (preprocess + format) handle the messy human interface so the four core nodes always operate on clean, structured input.

```
User input (potentially mixed DE/EN, typos, compound questions)
  → preprocess_query    — normalize language, extract entities, decompose compound queries
    → classify_query    — intent routing: entity_lookup | vessel_lookup | guidance_search | regulation_check | hybrid
      → execute_sql     — structured entity/vessel lookup (fuzzy matching, relationship traversal)
      → retrieve_docs   — ensemble retrieval (BM25 + semantic via pgvector + RRF merge)
      → [both]          — hybrid queries run SQL and retrieval in parallel
        → synthesize    — merge results from whichever path(s) ran, generate response with inline citations
          → format_response — enforce citation format, add data vintage, translate back if source language ≠ EN
            → User
```

### Node Details

**preprocess_query** — Single LLM call that takes raw analyst input and produces structured output:
- Language normalization: rewrites to English (preserving entity names exactly as typed)
- Entity extraction: pulls out entity names, vessel names, regulation references, article numbers
- Query decomposition: splits compound questions into atomic sub-queries with intent hints
- Spelling correction: fuzzy-matches against known entity names and regulatory terms
- Output: `{ original_query, normalized_query, entities[], regulations_referenced[], sub_queries[], source_language }`

**classify_query** — Routes each (sub-)query to the correct data source. Receives clean structured input from preprocessing, not raw user text. Intent categories: `entity_lookup | vessel_lookup | guidance_search | regulation_check | hybrid`. Includes confidence score; falls back to hybrid if confidence < threshold.

**execute_sql** — Generates and runs SQL against PostgreSQL structured tables. Handles entity lookups (fuzzy name matching via pg_trgm), vessel lookups (by IMO, name, or owner), and relationship traversal (entity_relationships table for 50% Rule chains). Returns structured results with data_vintage.

**retrieve_docs** — Ensemble retriever: runs BM25 (PostgreSQL full-text search) and semantic search (pgvector) in parallel, merges via Reciprocal Rank Fusion. Supports metadata filtering by jurisdiction, document_type, date range. Returns top-k chunks with full metadata (source, article_reference, data_vintage).

**synthesize** — Merges results from SQL and/or retrieval paths. LLM generates a response with inline citations linking every factual claim to a specific source document and passage. Clearly labels which jurisdiction each finding applies to (US/EU/DE). Proactively references applicable General Licenses or EU derogations when identifying blocked activities.

**format_response** — Lightweight post-processing:
- Enforces citation format consistency
- Adds data vintage disclaimer per source consulted
- Translates response to analyst's source language if needed (keeping regulatory terms and citations in original language)
- Flags when response draws from multiple jurisdictions

### Conversation Memory

ConversationBufferWindowMemory (window=5 messages). Follow-up questions use prior context. Memory is injected into preprocess_query so decomposition accounts for conversation history (e.g., "What about under EU law?" resolves the implicit entity from the previous turn).

## Database Schema (PostgreSQL + pgvector)

### Structured Entity Tables

```sql
-- Core sanctions entity table
-- Supports OFAC SDN, EU Consolidated List, Non-SDN, and Reg. 269/2014 listings
CREATE TABLE sanctioned_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,            -- 'ofac_sdn', 'eu_consolidated', 'ofac_nonsdn', 'eu_269'
    source_id TEXT NOT NULL,         -- Original list ID (OFAC entry_id, EU entity reference)
    entity_type TEXT NOT NULL,       -- 'individual', 'entity', 'vessel', 'aircraft'
    primary_name TEXT NOT NULL,
    programs TEXT[],                 -- OFAC: ['RUSSIA-EO14024', 'UKRAINE-EO13662']
    legal_basis TEXT[],              -- EU: ['Reg. 269/2014', 'Reg. 833/2014'] — separate from programs
                                     -- because EU uses regulation references, not program codes
    -- Individual-specific fields
    date_of_birth DATE,              -- Primary matching field for individuals. First thing analysts
                                     -- check on a fuzzy name match to confirm/rule out.
    nationality TEXT[],              -- Critical for EU sanctions: Reg. 833/2014 Art. 5b applies to
                                     -- Russian nationals regardless of residence. Array because
                                     -- individuals can hold multiple nationalities.
    -- Entity-specific fields
    country_of_registration TEXT,    -- Country of incorporation/registration. Determines which
                                     -- jurisdiction's restrictions apply. Not the same as address.
    remarks TEXT,
    list_date DATE,
    last_updated TIMESTAMP NOT NULL,
    data_vintage TIMESTAMP NOT NULL, -- When this data was fetched from source
    raw_record JSONB,                -- Full original record for audit
    UNIQUE(source, source_id)
);

-- Entity type mapping notes:
-- OFAC source data has finer distinctions (organization, government entity, etc.)
-- We normalize to: 'individual', 'entity', 'vessel', 'aircraft'
-- The original OFAC entity sub-type is preserved in raw_record JSONB
-- Queries scoped to "government-owned entities" or "state-owned banks" should
-- search raw_record->>'entity_sub_type' or use the RAG layer for richer context

-- Alternative names / aliases
CREATE TABLE entity_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID REFERENCES sanctioned_entities(id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    alias_type TEXT,                 -- 'aka', 'fka', 'nka'
    is_primary BOOLEAN DEFAULT FALSE
);

-- Vessel-specific data (OFAC designated vessels)
CREATE TABLE vessels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID REFERENCES sanctioned_entities(id) ON DELETE CASCADE,
    vessel_name TEXT,                -- Current/designated vessel name. Stored separately from
                                     -- parent entity primary_name because vessels get renamed
                                     -- as an evasion tactic. Name at designation time may differ
                                     -- from current name.
    imo_number TEXT,
    mmsi_number TEXT,
    vessel_type TEXT,
    flag TEXT,                        -- Current flag state. Note: flag can change (reflagging is
                                     -- a common evasion tactic). Flag at designation time may differ.
                                     -- v2: Add flag_history table or log flag changes across ingestion
                                     -- runs. Raw material exists in raw_record JSONB + ingestion_log.
    tonnage TEXT,
    build_year INTEGER,              -- Vessel age is a risk indicator — the Russia shadow fleet is
                                     -- disproportionately older vessels. Enables age-based filtering.
    call_sign TEXT
);

-- Entity addresses
CREATE TABLE entity_addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID REFERENCES sanctioned_entities(id) ON DELETE CASCADE,
    address TEXT,
    city TEXT,
    country TEXT,
    postal_code TEXT
);

-- Entity identifiers (passport numbers, tax IDs, etc.)
CREATE TABLE entity_identifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID REFERENCES sanctioned_entities(id) ON DELETE CASCADE,
    id_type TEXT NOT NULL,
    id_value TEXT NOT NULL,
    country TEXT
);

-- Entity-to-entity relationships (critical for 50% Rule / ownership chains)
-- If Entity A (on SDN list) owns 50%+ of Entity B (not listed), Entity B is
-- still blocked under OFAC's 50% Rule. Tracing these chains is one of the
-- hardest parts of sanctions screening and a major differentiator for this tool.
--
-- Populated from: OFAC remarks/linked entity references, EU XML relationship
-- fields. Coverage will be partial — the RAG layer supplements with enforcement
-- doc mentions. Hybrid approach: SQL for known relationships + semantic search
-- for contextual references.
CREATE TABLE entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_entity_id UUID REFERENCES sanctioned_entities(id) ON DELETE CASCADE,
    to_entity_id UUID REFERENCES sanctioned_entities(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,  -- 'owner', 'subsidiary', 'operates', 'linked_to'
    ownership_percentage NUMERIC,     -- NULL if unknown or not an ownership relationship
    notes TEXT,
    source TEXT,                      -- Where this relationship was extracted from
    UNIQUE(from_entity_id, to_entity_id, relationship_type)
);
```

### Vector Store Tables

```sql
-- Document chunks for RAG
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    embedding vector(1024),          -- Dimension depends on model; 1024 for bge-m3
    source_document TEXT NOT NULL,    -- S3 key or document identifier
    source_title TEXT,
    jurisdiction TEXT NOT NULL,       -- 'US', 'EU', 'DE'
    document_type TEXT NOT NULL,      -- 'enforcement', 'regulation', 'guidance', 'faq', 'general_license'
    article_reference TEXT,           -- e.g., 'Article 5b(1)' for regulations
    parent_chunk_id UUID,            -- For hierarchical chunking (v2)
    chunk_index INTEGER,             -- Position within document
    published_date DATE,
    ingestion_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    data_vintage TIMESTAMP NOT NULL,
    metadata JSONB                   -- Flexible additional metadata
);

-- HNSW index for vector similarity search
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Full-text search index for BM25-style retrieval
ALTER TABLE document_chunks ADD COLUMN tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX ON document_chunks USING gin (tsv);

-- Data freshness tracking
CREATE TABLE ingestion_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    ingestion_type TEXT NOT NULL,     -- 'full', 'incremental'
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    records_processed INTEGER,
    records_added INTEGER,
    records_updated INTEGER,
    records_removed INTEGER,
    status TEXT NOT NULL,             -- 'running', 'completed', 'failed'
    error_message TEXT,
    source_vintage TIMESTAMP          -- Timestamp of the source data itself
);
```

## Python Environment Management (uv)

This project uses **uv** for all Python dependency management, virtual environments, and script execution. Do not use pip, pip-tools, venv, or virtualenv directly.

### Project Layout

The repo has two separate Python packages, each with its own `pyproject.toml` and `uv.lock`:

- `backend/` — FastAPI app, agent, retrieval, LLM client
- `ingestion/` — Data ingestion pipeline, parsers, chunking, embedding

Each is an independent uv project. Work from within the relevant directory.

### Key Commands

```bash
# --- Setup ---
cd backend                        # or cd ingestion
uv sync                           # Install all deps from uv.lock (creates .venv automatically)

# --- Dependency Management ---
uv add fastapi pydantic           # Add a production dependency
uv add --dev pytest pytest-asyncio # Add a dev dependency
uv remove some-package            # Remove a dependency
uv lock                           # Regenerate uv.lock after manual pyproject.toml edits

# --- Running Code ---
uv run python -m app.main         # Run the FastAPI app
uv run uvicorn app.main:app --reload  # Run with uvicorn
uv run alembic upgrade head       # Run alembic migrations
uv run pytest                     # Run tests
uv run python scripts/ingest_all.py   # Run ingestion scripts

# --- Python Version ---
uv python install 3.13            # Install Python 3.13 if not present
uv python pin 3.13                # Pin version (writes .python-version)
```

### Rules

- **Always use `uv run`** to execute Python scripts and tools. This ensures the correct virtual environment and dependencies are used. Never activate the venv manually or call `python` directly.
- **Always use `uv add`** to add dependencies. Never `pip install`. This keeps `pyproject.toml` and `uv.lock` in sync.
- **Commit `uv.lock`** to git. This is the lockfile — it guarantees reproducible installs across machines.
- **Do not commit `.venv/`** directories. Add `.venv/` to `.gitignore`. uv recreates them from `uv.lock` via `uv sync`.
- **Pin the Python version** with `.python-version` at the repo root (e.g., `3.13`). uv respects this file.

### Dockerfiles

In Dockerfiles, install uv first, then use it to install dependencies:

```dockerfile
FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Install dependencies (no venv needed in container)
RUN uv sync --frozen --no-dev

COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Coding Standards

### Python (Backend + Ingestion)

- **Python 3.13+**
- **Async everywhere** in the backend (FastAPI, SQLAlchemy async, httpx)
- **Type hints on all function signatures.** Use `from __future__ import annotations` for cleaner forward references.
- **Pydantic v2** for all request/response schemas and settings. Use `model_validator` for complex validation.
- **SQLAlchemy 2.0 style** — use `select()` statements, not legacy Query API.
- **Alembic** for all schema changes. Never modify the database schema manually.
- **Environment variables** via `pydantic-settings`. Never hardcode secrets, API keys, or infrastructure endpoints.
- **Logging** via `structlog` — structured JSON logging. Include correlation IDs for request tracing.
- **Error handling**: Define domain-specific exceptions in `app/exceptions.py`. FastAPI exception handlers return structured error responses.
- **No business logic in route handlers.** Routes call services/agent, services call repositories. Keep layers clean.

### Linting & Formatting (ruff)

All Python code is linted and formatted by **ruff**. It replaces flake8, isort, black, and pyflakes in a single tool. ruff is a dev dependency in both `backend/` and `ingestion/`.

```bash
uv run ruff check .               # Lint
uv run ruff check . --fix         # Lint + auto-fix
uv run ruff format .              # Format (replaces black)
```

**ruff configuration** lives in each package's `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "W",     # pycodestyle warnings
    "F",     # pyflakes
    "I",     # isort (import sorting)
    "N",     # pep8-naming
    "UP",    # pyupgrade (modernize syntax)
    "B",     # flake8-bugbear (common gotchas)
    "SIM",   # flake8-simplify
    "ASYNC", # flake8-async (async anti-patterns)
    "S",     # flake8-bandit (security)
    "T20",   # flake8-print (no print statements — use structlog)
]
ignore = [
    "S101",  # allow assert in tests
]

[tool.ruff.lint.isort]
known-first-party = ["app"]       # backend; use ["pipeline"] for ingestion

[tool.ruff.format]
quote-style = "double"
```

**Rules:**
- All code must pass `uv run ruff check .` and `uv run ruff format --check .` before commit.
- Never disable a ruff rule inline (`# noqa`) without a comment explaining why.
- The `T20` rule bans `print()` statements — use `structlog` for all output. This catches accidental debug prints before they hit production.

### Naming Conventions

- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- API endpoints: `kebab-case` in URLs, `snake_case` in Python
- Database tables: `snake_case`, plural (`sanctioned_entities`, `document_chunks`)
- Environment variables: `UPPER_SNAKE_CASE` with prefix `SSA_` (e.g., `SSA_LLM_BASE_URL`)

### Testing

- **pytest** with `pytest-asyncio` for async tests. Always run via `uv run pytest`.
- Test structure mirrors source structure: `test_agent/`, `test_api/`, `test_retrieval/`
- **Fixtures** in `conftest.py` at each test directory level
- Integration tests use a test PostgreSQL database (Docker via `docker-compose.test.yml`)
- The `eval/` directory is separate from unit tests — it runs retrieval quality evaluations against the domain expert's query set
- Run evals: `uv run python tests/eval/run_eval.py`

### Git Conventions

- Branch naming: `feature/`, `fix/`, `refactor/`, `docs/`
- Commit messages: imperative mood, concise. e.g., `Add OFAC SDN ingestion pipeline`, `Fix entity alias deduplication`
- PR descriptions reference the task_plan.md task number

## Key Domain Concepts (for code context)

These are not legal definitions — they are simplified descriptions to help generate contextually appropriate code.

- **OFAC SDN List**: US Treasury's list of sanctioned persons/entities. ~12,000 entries. The primary US sanctions list. Pipe-delimited CSV format.
- **EU Consolidated Financial Sanctions List**: EU equivalent. ~4,000–6,000 entries. XML format from the European Commission.
- **Reg. 833/2014**: EU regulation imposing sectoral sanctions on Russia (trade, finance, energy). Amended 20+ times. The consolidated version from EUR-Lex is the source of truth.
- **Reg. 269/2014**: EU regulation listing individual persons/entities subject to asset freezes. The EU's equivalent of naming specific people/companies (like the SDN list names individuals).
- **OFAC General Licenses (GLs)**: Authorizations that allow specific categories of transactions that would otherwise be blocked. Critical for answering "can we do this?" questions. Without them, the tool can say what's blocked but not what's authorized.
- **50% Rule**: OFAC rule that entities owned 50% or more by blocked persons are themselves treated as blocked, even if not on the SDN list.
- **Data vintage**: The timestamp indicating when source data was last fetched. EVERY response must surface this. An analyst acting on stale data faces the same regulatory risk as not screening at all.
- **Vessel designations**: OFAC designates specific vessels by IMO number. Maritime sanctions (especially Russia oil price cap) are a major analyst workload.
- **Dual-jurisdiction**: European banks in USD markets must comply with both OFAC (US) and EU sanctions simultaneously. Restrictions can differ — an entity may be sanctioned under one regime but not the other.

## Critical Constraints

1. **Privacy is non-negotiable.** In self-hosted mode, zero external API calls. No telemetry, no cloud embeddings, no third-party LLM APIs. Everything runs within the VPC.
2. **Every response must cite its sources.** Include document name, section/article reference, and data vintage timestamp. Unsourced claims are unacceptable in compliance.
3. **The LLM is a swappable component.** All code must work identically whether the LLM is Mistral cloud API, Ollama local, or vLLM production. Never use provider-specific features that break portability.
4. **Data freshness matters.** Sanctions list data must be no more than 48 hours old in production. Every API response includes metadata showing the vintage of each source consulted.
5. **This is a research assistant, not a screening system.** It does not access bank transaction data. It does not make compliance decisions. It provides sourced information for analysts to use in their own decision-making.
6. **Mixed language corpus.** Documents are in English and German, with EU legal terminology. The embedding model and retrieval pipeline must handle multilingual content.

## Data Refresh Cadences

Stale data is an operational risk. An analyst acting on outdated sanctions list data faces the same regulatory exposure as not screening at all. The ingestion pipeline must enforce these cadences, and every response must surface the data vintage.

| Source | Refresh | Rationale |
|---|---|---|
| OFAC SDN List / Non-SDN List | Daily (automated) | Designations take effect immediately upon publication. Delay > 48 hours = screening gap. |
| OFAC Designated Vessels | Daily (automated, bundled with SDN) | Published alongside SDN updates. Operationally critical for maritime sanctions. |
| EU Consolidated Financial Sanctions List | Daily (automated) | Council Implementing Regulations can be published at any time. |
| OFAC General Licenses | Weekly (automated + manual review) | New GLs are issued periodically. Weekly check is sufficient, but new GLs trigger an alert for manual review. |
| Reg. 833/2014 (Consolidated) | After each amendment (weekly automated check + manual trigger) | Amendments via EU Council Decisions, typically every 2–4 months. Check EUR-Lex weekly for new consolidated versions. |
| Reg. 269/2014 (Consolidated) | After each amendment (same cadence as 833/2014) | Individual designation amendments follow a similar schedule. |
| EU Commission FAQs | Monthly (automated check) | Updated periodically as new questions arise. Monthly is sufficient. |
| OFAC Enforcement Actions | Monthly (automated check) | Published as they occur. Monthly captures new settlements. |
| OFAC FAQs / Advisories / Compliance Framework | Monthly (automated check) | Updated periodically. Monthly ensures coverage. |
| Bundesbank / BaFin / Ministry Guidance | Quarterly (manual review) | German guidance changes infrequently. Quarterly with alerts for known updates. |

**Implementation rules:**
- Every ingested document/record must carry `data_vintage` (when the source data was fetched) and `ingestion_timestamp` (when it was processed).
- Every API response must include a metadata field showing the vintage of each source consulted.
- Ingestion failures must trigger immediate notification (log alert at minimum, email/Slack for production).
- If a daily source hasn't changed in >3 days, flag as potential fetch failure (the source may have changed but the download broke silently).

## Development Workflow

1. Local development uses `docker-compose.yml` for PostgreSQL + pgvector. The app runs on the host via `uv run`.
2. Setup: `cd backend && uv sync` (or `cd ingestion && uv sync`) to install deps and create `.venv`
3. Run the backend: `cd backend && uv run uvicorn app.main:app --reload`
4. Run ingestion: `cd ingestion && uv run python scripts/ingest_all.py`
5. Run migrations: `cd backend && uv run alembic upgrade head`
6. LLM calls go to Mistral cloud API during development (configured via env vars)
7. Run tests: `cd backend && uv run pytest`
8. Run retrieval evals: `cd backend && uv run python tests/eval/run_eval.py`
9. Lint before commit: `uv run ruff check . --fix && uv run ruff format .`

### AI Coding Tools

This project uses Claude Code and/or Codex as the primary development tool. This CLAUDE.md provides project-specific context (tech stack, schema, domain, conventions). The **Superpowers plugin** may also be installed to enforce development process discipline (brainstorm → plan → TDD → review). The two layers are complementary:
- **This file** = what to build and how it should look
- **Superpowers** = when to stop, plan, test, and review

For well-specified tasks from the task_plan.md, skip the Superpowers brainstorming phase and go straight to planning or implementation.

## Common Tasks

### Adding a new data source
1. Create a new parser in `ingestion/pipeline/sources/`
2. Add chunking logic (use existing text_chunker or create document-specific chunker)
3. Add source-specific metadata tags
4. Register in `ingestion/pipeline/runner.py`
5. Run ingestion: `cd ingestion && uv run python scripts/ingest_all.py`
6. Verify chunks in database, test retrieval

### Adding a new Python dependency
```bash
cd backend  # or cd ingestion
uv add package-name              # Production dep
uv add --dev package-name        # Dev/test dep
# uv.lock updates automatically — commit both pyproject.toml and uv.lock
```

### Adding a new agent capability
1. Define the new node in `backend/app/agent/nodes/`
2. Add the routing condition in `backend/app/agent/graph.py`
3. Add prompt template in `backend/app/agent/prompts/`
4. Update the classify_query prompt to recognize the new intent
5. Add eval queries for the new capability

### Modifying the database schema
1. Modify SQLAlchemy models in `backend/app/db/models.py`
2. Generate migration: `cd backend && uv run alembic revision --autogenerate -m "description"`
3. Review the generated migration file
4. Apply: `cd backend && uv run alembic upgrade head`
