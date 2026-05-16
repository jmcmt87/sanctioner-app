# Progress Log — Sanctions Screening Assistant

## 2026-05-16 — Session 11: Domain Expert Feedback (models.py) + Source Documentation

### Completed: Implemented domain expert feedback on models.py + wrote sanctions domain documentation

**Domain Expert Feedback — Vessel IMO Uniqueness**
- Added partial composite unique index `ix_vessels_imo_entity_unique` on `(imo_number, entity_id) WHERE imo_number IS NOT NULL`
- A simple unique on `imo_number` alone failed: TASCA (IMO 9313149) is legitimately listed under both Russia/Ukraine (EO14024) and Iran (EO13846) programs as separate SDN entries
- The composite index prevents the same vessel from being duplicated under the same parent entity while allowing valid cross-program designations
- New Alembic migration: `a06fa9eb0762_add_partial_unique_index_on_vessels_imo_.py`
- Model updated with `__table_args__` using `Index()` with `postgresql_where`

**Domain Expert Feedback — tsv tsvector Column**
- Confirmed already handled: existing migration `930864a558eb` (lines 142-149) creates the generated column + GIN index via raw SQL
- No changes needed; SQLAlchemy doesn't handle `GENERATED ALWAYS AS` natively, so the migration approach is correct

**Source Documentation (Sanctions Domain Perspective)**
- Rewrote `ingestion/pipeline/sources/README.md` from ~48 lines to ~280 lines
- Each implemented source (OFAC SDN, OFAC Non-SDN, EU Consolidated) now documented with:
  - What the source is (regulatory authority, legal basis, consequence of designation)
  - Entity composition with actual record counts from the database
  - Program/regime distributions (top 10 with record counts)
  - Field coverage stats (% populated per field, compliance significance)
  - Related table statistics (aliases, addresses, identifiers, vessels, relationships)
  - How compliance analysts use it (specific questions it answers)
  - Source format details and refresh rationale
- Added sections on planned sources (General Licenses, Enforcement, EU Regulations, Guidance)
- Added cross-source relationships section (dual-jurisdiction comparison table, known overlaps, current gaps)
- Updated `ingestion/README.md` reference to the expanded documentation

### Blockers / Notes
- Non-SDN record count (442 vs. expected ~1,900) flagged by DQR agent — the source data file may be a subset; warrants investigation
- EU parser does not extract entity relationships (0 relationships vs. OFAC's 7,704) — known gap for future work

### Next step
- Continue with Phase 1.3 tasks: embedding model setup (1.3.1), PDF extraction (1.3.2), text chunking (1.3.3), enforcement PDF ingestion (1.3.4), OFAC guidance ingestion (1.3.5)
- Before starting 1.3, consider investigating the Non-SDN record count discrepancy (442 vs ~1,900 expected)
- Consider improving the relationship regex to handle "S.A.", "CO., LTD." suffixes (would recover ~200+ of the 908 unresolved references)

## 2026-05-16 — Session 10: Data Quality Review, Parser Fixes, Re-Ingestion, Testing

### Completed: Full data quality cycle — audit → fix → re-ingest → verify → test

**Data Quality Review Infrastructure**
- Created `.claude/agents/data-quality-reviewer.md` — custom subagent definition for database-level data quality auditing via MCP SQL tools
- Created `.claude/skills/data-quality-review/SKILL.md` — skill defining DQR report format, test entities, and quality metrics
- Created `.claude/agent-memory/data-quality-reviewer/` — 5 memory files: baselines for OFAC SDN, OFAC Non-SDN, EU Consolidated; parser gap analysis; index
- Ran full data quality review across all 6 dimensions (OFAC SDN, OFAC Non-SDN, EU Consolidated, encoding integrity, ingestion health, referential integrity)
- DQR reports saved to `.tmp/` (7 files: dqr-index.md + 6 dimension reports)

**EU Sanctions Parser Fixes**
- Fixed legal_basis regex: `\d{4}` → `\d+` — was dropping 46.8% of EU records' legal_basis (regulations with short-year format like `2020/716` or `36/2011`)
- Added Solar Hijri calendar date guard: `year < 1900` skip in both full-date and component-date branches — prevents non-Gregorian dates (e.g., SH year 1340) from being stored

**OFAC SDN Parser Enhancements**
- Added 13 new identifier patterns: C.U.R.P., R.F.C., USCC, SWIFT/BIC, Trade License, D.N.I., D-U-N-S, Enterprise Number, Driver's License, BIK, Phone Number, License
- Added Digital Currency Address extraction with special capture group handling
- Added inline a.k.a./f.k.a. alias extraction from remarks with case-insensitive dedup against alt.csv aliases
- Added `country_of_registration` extraction from "Nationality of Registration" in remarks for entity-type records
- Added `error_message` population when `records_skipped > 0` (both SDN and Non-SDN)

**Entity Relationship Extraction (NEW module)**
- Created `ingestion/pipeline/relationships.py` — extracts "Linked To:" references from OFAC remarks
- Regex-based extraction with case-insensitive resolution against primary_name and aliases
- Idempotent: deletes existing `ofac_remarks` relationships before re-creating
- ON CONFLICT DO NOTHING for the unique constraint, self-reference skip
- Integrated into `runner.py` — called after all source ingestion completes

**Upsert Module Enhancements**
- Added alias deduplication in upsert: set-based (alias_name.lower(), alias_type) dedup before insert
- Added EntityRelationship cleanup: deletes from_entity relationships before re-inserting child records

**Re-Ingestion Results**
- OFAC SDN: 18,959 records updated (7m 19s)
- OFAC Non-SDN: 442 records updated (11s)
- EU Consolidated: 5,996 records updated (2m 23s)
- Entity Relationships: 7,982 resolved out of 8,890 references (89.8% resolution rate)
- 908 unresolved — mostly company names truncated by the period-terminated regex (e.g., "AGRICOLA BOREAL S" instead of "AGRICOLA BOREAL S.A. DE C.V.")

**Data Quality Verification**
- EU legal_basis coverage: **99.7%** (was ~53%)
- Entity relationships: **7,982** (was 0)
- Entity identifiers: 18,395
- Entity aliases: 50,031
- Vessels: 1,480

**Test Suite (195 total, all passing)**
- `test_eu_sanctions_parsing.py` — 57 tests (added: Solar Hijri skip, short-year regulation)
- `test_ofac_sdn_parsing.py` — 73 tests (added: 10 identifier types, 5 inline alias, 3 country_of_registration, 3 alias dedup)
- `test_relationships.py` — 19 tests (NEW: regex, extraction, alias dedup)
- `test_hashing.py` — 12 tests
- `test_ofac_nonsdn.py` — 20 tests (NEW: source config, CSV parsing, comment aggregation, address/alias indexing)
- `test_runner.py` — 13 tests (NEW: source registration, file patterns, hash skip, relationship integration)
- `test_health.py` — 2 tests (backend)

**CLAUDE.md Condensed**
- Removed redundant full project structure tree (503 lines deleted, 114 added)
- Replaced with concise "Project Layout" section pointing to key locations
- All essential information preserved in more scannable format

### Blockers / Notes
- Relationship regex truncation: entity names ending with "S.A.", "C.A.", "CO., LTD." get truncated by the period-terminated regex `[^;.]+?`. Known limitation — 908 unresolved references. Fixable with a lookahead for common suffixes in a follow-up.
- The `completed_with_errors` status on OFAC SDN/Non-SDN is expected — 1 record skipped per source during parsing.

### Next step
- Continue with Phase 1.3 tasks: embedding model setup (1.3.1), PDF extraction (1.3.2), text chunking (1.3.3), enforcement PDF ingestion (1.3.4), OFAC guidance ingestion (1.3.5)
- Before starting 1.3, consider improving the relationship regex to handle "S.A.", "CO., LTD." suffixes (would recover ~200+ of the 908 unresolved references)

## 2026-05-16 — Session 9: PostgreSQL MCP Server Setup

### Completed: MCP server for read-only PostgreSQL access

**MCP Server Configuration**
- Created `.mcp.json` at project root configuring `@bytebase/dbhub` as the PostgreSQL MCP server
- Connects to `postgresql://postgres:postgres@localhost:5432/sanctions_db` (matches `docker-compose.yml`)
- Provides read-only SQL access to Claude Code and future subagents
- Intentionally avoided the deprecated `@modelcontextprotocol/server-postgres` (archived, has a SQL injection vulnerability allowing bypass of read-only restriction)

**Documentation Updates**
- `README.md` — Added "MCP Server (PostgreSQL)" section with prerequisites and verification instructions
- `backend/README.md` — Added MCP section explaining read-only agent access to the database
- `backend/app/db/README.md` — Added cross-reference to the MCP server for data quality workflows

### Blockers / Notes
- No blockers
- The MCP server requires Docker PostgreSQL to be running (`cd backend && docker compose up -d`)
- MCP tools become available in new Claude Code sessions (not the current one)

### Next step
- Create a data-quality-reviewer subagent in `.claude/agents/` that uses the MCP tools to inspect database contents
- Continue with Phase 1.3 tasks: embedding model setup (1.3.1), PDF extraction (1.3.2), text chunking (1.3.3), enforcement PDF ingestion (1.3.4), OFAC guidance ingestion (1.3.5)

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
