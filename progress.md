# Progress Log — Sanctions Screening Assistant

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

**What remains for 1.1.1:**
- `docker-compose.yml` with PostgreSQL 16 + pgvector
- Alembic initialization (`alembic init` + config)

### Notes
- Development machine is Intel Mac (x86_64) running macOS 26 / Python 3.13.5
- PyTorch/sentence-transformers cannot install natively — embedding work must run in Docker or on a different machine
- uv 0.10.8 installed via Homebrew
