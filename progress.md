# Progress Log — Sanctions Screening Assistant

## 2026-05-15 — Session 8: Architecture Audit (Documentation Focus) + READMEs

### Completed: Audit re-run + 6 READMEs following documentation-standard skill

**Architecture Audit (B+ grade, Conditional Pass)**
- Re-ran full architecture-auditor agent against all implemented code
- Report saved to `.tmp/audit_report_2026-05-15.md` (overwrites earlier report)
- No critical blockers; 5 important items (I1-I5) and 5 minor items (M1-M5)
- Audit specifically focused on documentation gaps to guide README creation

**Documentation — 6 READMEs created per documentation-standard skill**
- `README.md` (root, 92 lines) — Project overview, architecture diagram, quick start, env vars table, project structure
- `backend/README.md` (42 lines) — Backend overview, running commands, directory inventory, key decisions
- `backend/app/db/README.md` (37 lines) — Models overview, session management, schema modification guide
- `backend/tests/README.md` (39 lines) — Test organization, fixtures, how to run and add tests
- `ingestion/README.md` (66 lines) — Pipeline architecture, data directory layout, running scripts, key decisions
- `ingestion/pipeline/sources/README.md` (47 lines) — Source inventory table with status, adding a new source guide, parser details

All READMEs are within skill line limits (project <150, modules <80). Directories with only `__init__.py` were skipped per skill rule.

### Blockers / Notes
- No blockers
- Markdownlint warnings on `.tmp/audit_report_2026-05-15.md` (table column style) — cosmetic only, `.tmp/` is not committed

### Next step
- Continue with Phase 1.3 tasks: embedding model setup (1.3.1), PDF extraction (1.3.2), text chunking (1.3.3), enforcement PDF ingestion (1.3.4), OFAC guidance ingestion (1.3.5)
- Before starting 1.3, consider fixing I1 (extract shared ingestion orchestration wrapper) since the next parsers will benefit immediately

## 2026-05-15 — Session 7: Architecture Audit + Codebase Fixes

### Completed: Full architecture audit + fix all 9 audit findings

**Architecture Audit (B+ grade, Conditional Pass)**
- Ran architecture-auditor agent against `backend/app/`, `ingestion/pipeline/`, `backend/alembic/`, `backend/tests/`
- Checked all 12 areas: schema design, agent pipeline, retrieval, LLM abstraction, data vintage, citations, config, ingestion, testing, migrations, dependencies, code quality
- Full report saved to `.tmp/audit_report_2026-05-15.md`

**C1 — Eliminated duplicated SQLAlchemy models**
- `ingestion/pipeline/db_models.py` now re-exports from `app.db.models` (single source of truth)
- Added `sanctions-screening-backend` as a path dependency in ingestion's `pyproject.toml`
- The two copies had already diverged (ingestion was missing relationship back_populates)

**C2 — Extracted shared upsert logic (~400 lines of duplication removed)**
- Created `ingestion/pipeline/upsert.py` — shared `upsert_entities()` function
- `ofac_sdn.py` lost ~130 lines, `ofac_nonsdn.py` lost ~130 lines, `eu_sanctions.py` lost ~120 lines
- Standardized child record format (`aliases`, `addresses`, `identifiers`, `vessels`) across all parsers
- Future parsers just parse → produce standard dicts → call `upsert_entities()`

**I1 — Fixed S3Client.has_changed() async/sync mismatch**
- Changed from `async def` to `def` since it only calls sync boto3 methods

**I2 — Replaced bare except Exception in parsers**
- Created `ingestion/pipeline/exceptions.py` with `RecordParseError`
- OFAC parsers now catch `RecordParseError` instead of swallowing all exceptions

**I4 — Consolidated backend dev dependencies**
- Merged split `[project.optional-dependencies].dev` and `[dependency-groups].dev` into single `[dependency-groups].dev`

**I5 — Added missing noqa comment**
- `eu_sanctions.py` line 51: `# noqa: S320 -- trusted local file from known EU source`

**M1 — Excluded alembic/versions from ruff**
- Added `extend-exclude = ["alembic/versions"]` to backend ruff config

**M4 — Fixed conftest return type**
- Updated fixture annotation to `AsyncGenerator[AsyncClient]`

**M5 — Resolved duplicate compute_file_hash**
- Added `compute_content_hash(bytes)` to `hashing.py`
- `loaders.py` now imports from `hashing` instead of defining its own

**All 114 tests pass (112 ingestion + 2 backend). Ruff clean on both packages.**
**Net: -240 lines of duplicated code, +170 lines of shared infrastructure.**

### Blockers / Notes
- No blockers
- `uv sync --reinstall` needed after adding the path dependency (`.pth` file not picked up until reinstall)
- The path dep pulls backend's heavy deps (fastapi, langgraph, etc.) into ingestion's venv — acceptable for dev, could extract a shared models package later if container size matters

### Next step
- Continue with Phase 1.3 tasks: embedding model setup (1.3.1), PDF extraction (1.3.2), text chunking (1.3.3), enforcement PDF ingestion (1.3.4), OFAC guidance ingestion (1.3.5)

## 2026-05-15 — Session 6: Test Suite for Existing Code

### Completed: Unit tests for backend + ingestion (112 tests, all passing)

**Backend tests (2 tests)**
- Created `backend/tests/conftest.py` — AsyncClient fixture with ASGI transport (httpx, per testing skill standards)
- Created `backend/tests/test_api/test_health.py` — Health endpoint returns 200 + correct body

**Ingestion tests — OFAC SDN parsing (44 tests)**
- Created `ingestion/tests/test_ofac_sdn_parsing.py`
- Covers all pure parsing functions: `_clean` (5), `_parse_csv` (4), `_parse_dob` (7), `_parse_nationalities` (4), `_parse_programs` (5), `_parse_identifiers` (5), `_normalize_entity_type` (5), `_build_entity_dict` (9)
- Tests entity, individual (DOB, nationality), and vessel (IMO, MMSI, build_year) parsing paths
- Tests null sentinel handling, extended remarks, empty programs, alias/address preservation

**Ingestion tests — EU Sanctions XML parsing (50 tests)**
- Created `ingestion/tests/test_eu_sanctions_parsing.py`
- Covers all XML parsing functions: `_attr` (4), `_normalize_entity_type` (3), `_parse_date` (4), `_extract_primary_name` (5), `_extract_citizenships` (3), `_extract_birthdate` (5), `_extract_addresses` (3), `_extract_identifications` (4), `_extract_regulations` (5), `_extract_remarks` (3), `_build_entity_dict` (9), `_parse_xml` (2)
- Tests primary name selection strategy (English strong > any strong > first available)
- Tests legal_basis extraction from regulation numberTitle, deduplication, earliest publication date tracking
- Tests error handling: missing euReferenceNumber, missing name

**Ingestion tests — Hashing module (16 tests)**
- Created `ingestion/tests/test_hashing.py`
- Covers: `compute_record_hash` (4), `compute_file_hash` (3), `compute_source_hash` (3), `HashStore` (6)
- Tests determinism, key-order independence, disk persistence, multi-source independence

**All code passes ruff check + ruff format in both packages.**

### Blockers / Notes
- No blockers encountered
- Backend has minimal testable logic beyond health endpoint (agent, repositories, retrieval, routers not yet implemented)
- Integration tests for full ingestion pipeline (DB-level) deferred — need testcontainers + running Docker
- `httpx` is already a production dependency in backend; `testcontainers[postgres]` already in dev deps

### Next step
- Continue with Phase 1.3 tasks: embedding model setup (1.3.1), PDF extraction (1.3.2), text chunking (1.3.3), enforcement PDF ingestion (1.3.4), OFAC guidance ingestion (1.3.5)
- As each new component is built, write tests immediately per the testing skill standard

## 2026-05-15 — Session 5: Phase 1 Foundation + Structured Data Ingestion

### Completed: Tasks 1.1.2–1.1.4 and 1.2.1–1.2.5

**Task 1.1.4 — Configuration management**
- Created `backend/app/config.py` — pydantic-settings `Settings` class with all `SSA_`-prefixed env vars (DB, LLM, S3, embedding, observability)
- Created `backend/app/logging.py` — structlog setup with JSON rendering, timestamping, log level from config
- Created `backend/app/exceptions.py` — domain-specific exception hierarchy
- Created `backend/app/main.py` — FastAPI app entry point with health endpoint

**Task 1.1.2 — Database schema: structured entity tables**
- Created `backend/app/db/models.py` — 8 SQLAlchemy models: `SanctionedEntity`, `EntityAlias`, `Vessel`, `EntityAddress`, `EntityIdentifier`, `EntityRelationship`, `DocumentChunk`, `IngestionLog`
- All models follow skill patterns: UUID PKs with `server_default`, `TIMESTAMP(timezone=True)`, `ARRAY(Text)`, proper `relationship()` with `back_populates`
- Created `backend/app/db/session.py` — async session factory
- Alembic migration for extensions (pgvector + pg_trgm) + all tables
- Manual indexes: HNSW on embeddings, GIN on tsvector (generated column), trigram on `primary_name` and `alias_name`
- Full migration roundtrip verified (downgrade base → upgrade head)

**Task 1.1.3 — Database schema: vector store tables**
- `document_chunks` table with `vector(1024)` column, generated `tsvector` column, HNSW + GIN indexes
- Completed as part of the same migration as 1.1.2

**Task 1.2.1 — OFAC SDN list ingestion**
- Created `ingestion/pipeline/sources/ofac_sdn.py` — full parser following six-step ingestion pattern
- Parses 4 CSV files: `sdn.csv` (18,960 rows), `add.csv` (24,737), `alt.csv` (20,297), `sdn_comments.csv` (32)
- Extracts: DOB from remarks, nationality, identifiers (passport, tax ID, etc.), vessel IMO/MMSI/build_year
- Entity type normalization: `-0-` → `entity`, plus `individual`, `vessel`, `aircraft`
- Upsert via `INSERT ... ON CONFLICT DO UPDATE`, children deleted and re-inserted
- **Result: 18,959 entities loaded** (9,670 entities, 7,465 individuals, 1,480 vessels, 344 aircraft), 20,296 aliases, 21,522 addresses, 12,722 identifiers

**Task 1.2.2 — EU Consolidated Financial Sanctions List ingestion**
- Created `ingestion/pipeline/sources/eu_sanctions.py` — XML parser using lxml
- Parses 24MB XML with namespace `http://eu.europa.ec/fpi/fsd/export`
- Extracts: nameAliases (primary = English strong alias), citizenship → nationality, birthdate, addresses, identifiers, regulation → legal_basis, programme → programs
- **Result: 5,996 entities loaded** (4,410 individuals, 1,586 entities), 24,277 aliases, 2,443 addresses, 2,615 identifiers

**Task 1.2.3 — OFAC Non-SDN list ingestion**
- Created `ingestion/pipeline/sources/ofac_nonsdn.py` — reuses SDN parsing helpers with different source name and file paths
- **Result: 442 entities loaded**

**Task 1.2.4 — Incremental update logic**
- Created `ingestion/pipeline/hashing.py` — `HashStore` class for SHA-256 hash-based file change detection
- Integrated into `ingestion/pipeline/runner.py` — skips unchanged sources entirely
- Verified: second run with unchanged files correctly skips all sources

**Task 1.2.5 — S3 integration**
- Created `ingestion/pipeline/loaders.py` — `S3Client` (upload/download/list/hash comparison), `acquire_direct_download()` helper, `download_file()` with retry logic
- S3 key convention: `raw/{category}/{source_name}/{YYYY-MM-DD}/{filename}`
- httpx async client with custom User-Agent, 3 retries with exponential backoff

**Infrastructure created:**
- `ingestion/pipeline/config.py` — IngestionConfig (pydantic-settings)
- `ingestion/pipeline/db.py` — async session factory for ingestion
- `ingestion/pipeline/db_models.py` — re-exports from `app.db.models` (consolidated in Session 7)
- `ingestion/pipeline/models.py` — IngestionResult and AcquisitionResult Pydantic models
- `ingestion/pipeline/runner.py` — orchestrator with `REGISTERED_SOURCES` registry
- `ingestion/scripts/ingest_all.py`, `ingest_incremental.py`, `ingest_ofac_sdn.py`, `ingest_ofac_nonsdn.py`, `ingest_eu_sanctions.py`

**Total: 25,397 sanctioned entities across 3 sources in the database.**

**What remains for Phase 1:** Tasks 1.3.1–1.3.5 (embedding model setup, PDF extraction, text chunking, enforcement PDF ingestion, OFAC guidance ingestion).

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
