# Progress Log — Sanctions Screening Assistant

## 2026-05-14 — Session 4: Architecture Audit + Fixes

### Completed: Full architecture audit + fix all findings

**Audit ran against:** `backend/app/`, `ingestion/pipeline/`, `backend/alembic/`, `backend/tests/`, project root.
**Verdict:** CONDITIONAL PASS — scaffolding well-organized, two critical blockers found and fixed.

**Critical fixes (blocked task 1.1.2):**
- Created `backend/docker-compose.yml` — PostgreSQL 16 + pgvector, matching `SSA_DATABASE_URL` from `.env.example`
- Initialized Alembic — `alembic.ini`, `alembic/env.py` (async SQLAlchemy, reads `SSA_DATABASE_URL` via `app.config.settings`), `alembic/script.py.mako`

**CLAUDE.md consistency fixes (both project + parent copies):**
- LLM env var prefix: `LLM_BASE_URL` → `SSA_LLM_BASE_URL` (and `MODEL_NAME`, `API_KEY`)
- Ruff `target-version`: `py312` → `py313` to match actual config
- Added `exceptions.py` to file tree (referenced in coding standards but missing from tree)
- Added `pipeline/models.py` to file tree (defined in ingestion-pipeline-patterns skill)

**Dependency and config fixes:**
- Added `testcontainers[postgres]` to backend dev dependencies
- Added `beautifulsoup4` to ingestion dependencies
- Added `pytest-cov` to ingestion dev dependencies
- Added `testpaths = ["tests"]` to ingestion pytest config
- Removed empty `[tool.uv]` section from `ingestion/pyproject.toml`
- Created `ingestion/tests/` directory

**Other:**
- Created `README.md` at repo root with quick-start instructions
- Full audit report saved to `.tmp/audit_report_2026-05-14.md`

**Task 1.1.1 is now COMPLETE.** All acceptance criteria met: directory structure, uv projects, docker-compose, Alembic config.

## 2026-05-14 — Session 3: Auditor Improvements + Builder Skills

### Completed: Phase 1 deliverables — agent/skill overhaul

**What was done:**

Improvements to existing files:
- **`.claude/agents/architecture-auditor.md`** — Replaced hardcoded absolute paths with relative paths, added PHASE-AWARE AUDITING section (only audit what exists, don't flag planned-but-unbuilt components), replaced Critical/Warnings/Suggestions with phase-aware severity tiers (Fix Before Next Phase / Fix Within Current or Next Phase / Backlog), added "What's Good" section to reinforce good patterns, added 6 code-level review checks (type hints, async consistency, error handling, duplication, naming, raw SQL)
- **`.claude/skills/software-architect-review/SKILL.md`** — Removed B.L.A.S.T. reference, expanded bias rule 2 to distinguish dictionary-based registration patterns (acceptable from the start) from class hierarchies (wait for 2+ implementations)
- **`.claude/skills/software-architect-review/references/review-framework.md`** — Added General License / EU derogation red flag to Domain-Specific Red Flags, added REJECTED verdict guidance with escalation instructions (Deniz for architecture, Marc for scope)
- **`.claude/skills/software-architect-review/references/extensibility-patterns.md`** — Replaced class-based `OFACSdnParser` example with function-based `ingest_ofac_sdn` pattern matching CLAUDE.md conventions, added note on when to introduce protocol/base class (6+ sources)

New builder skills added:
- **`ingestion-pipeline-patterns`** — Six-step ingestion pattern (download → parse → validate → map → upsert → log), IngestionResult model, error handling rules, file structure convention, runner registry pattern
- **`sqlalchemy-alembic-patterns`** — Model conventions (column patterns, relationships, unique constraints, naming), index setup (HNSW, GIN, trigram), async session factory, dependency injection, repository pattern, Alembic migration conventions
- **`data-acquisition-patterns`** — Three acquisition categories (direct download, index crawl, HTML extraction), standard function signature, httpx client rules, rate limiting, retry logic, S3 organization, hash-based change detection, manifest tracking

**7 files changed (4 modified, 3 created).**

## 2026-05-14 — Session 2: Claude Code Tooling Setup

### Completed: Adapt agent and skills from lingual-app to sanctioner-app

**What was done:**
- Rewrote `.claude/agents/architecture-auditor.md` for the sanctions screening domain
  - Audit phases now cover: LangGraph six-node pipeline, pgvector schema, LLM abstraction, data vintage compliance, citation enforcement, dual-jurisdiction checks, 50% Rule support
  - Paths updated from lingual-app to sanctioner-app
- Rewrote `.claude/skills/software-architect-review/` (SKILL.md + 3 reference files)
  - Layer architecture updated: `routers → agent graph → nodes → repositories → models`
  - Extensibility patterns cover intent routing registry, source-agnostic ingestion, jurisdiction parameters
  - Red flags checklist includes domain-specific checks (data vintage, citations, vessel IMO, 50% Rule)
  - Architect bias rules added for LLM swappability and mandatory source citations
- Rewrote `.claude/skills/fastapi-testing/` (SKILL.md + 3 reference files)
  - Renamed `lingual-app-priorities.md` → `sanctioner-app-priorities.md`
  - Test priorities: agent nodes → repositories → retrieval pipeline → routers → ingestion parsers
  - LLM mocking fixtures for classify, preprocess, synthesize responses (replaces Claude/Anthropic mocking)
  - Data vintage propagation tests added as explicit test category
  - Test fixtures use `pgvector/pgvector:pg16` container with `pg_trgm` extension
  - Factory helpers create `SanctionedEntity` and `Vessel` instead of users/exercises
- Updated `.claude/commands/audit.md` scope to match sanctioner-app directories
- Commit: `8cc8b7c`

**10 files changed, 1668 lines added.**

## 2026-05-14 — Session 1: Project Scaffolding

### Completed: Task 1.1.1 (Partial) — Initialize repository structure

**What was done:**
- Created full monorepo directory structure: `backend/`, `ingestion/`, `frontend/`, `infra/`, `docs/`
- Initialized `backend/` as independent uv project (`pyproject.toml` + `uv.lock`)
  - Dependencies: FastAPI, SQLAlchemy (async), Alembic, LangChain, LangGraph, LangSmith, pgvector, structlog, httpx, Pydantic v2, websockets, uvicorn
  - Dev deps: pytest, pytest-asyncio, pytest-cov, ruff, mypy
  - 83 packages installed
- Initialized `ingestion/` as independent uv project (`pyproject.toml` + `uv.lock`)
  - Dependencies: SQLAlchemy (async), LangChain, langchain-text-splitters, pgvector, structlog, boto3, lxml, httpx, Pydantic v2
  - Dev deps: pytest, pytest-asyncio, ruff
  - 71 packages installed
  - `sentence-transformers` set as optional extra (`uv sync --extra embeddings`) — PyTorch lacks Intel Mac x86_64 wheels for Python 3.13
- Pinned Python 3.13 (updated from 3.12 in CLAUDE.md spec)
- Created `.env.example` with all `SSA_`-prefixed environment variables
- Created `.gitignore`
- Created all `__init__.py` files for package structure
- Configured ruff (linting + formatting) in both `pyproject.toml` files per CLAUDE.md spec
- Configured pytest with `asyncio_mode = "auto"` in both packages
- Initial commit: `df99c16`

**What remained for 1.1.1 (completed in Session 4):**
- ~~`docker-compose.yml` with PostgreSQL 16 + pgvector~~
- ~~Alembic initialization (`alembic init` + config)~~

### Notes
- Development machine is Intel Mac (x86_64) running macOS 26 / Python 3.13.5
- PyTorch/sentence-transformers cannot install natively — embedding work must run in Docker or on a different machine
- uv 0.10.8 installed via Homebrew
