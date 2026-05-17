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
| Embeddings | sentence-transformers (self-hosted) | Configurable via env vars. Dev: all-MiniLM-L6-v2 (384-dim, 90MB). Prod: BAAI/bge-m3 (1024-dim, 2.3GB) |
| Data Lake | AWS S3 | Raw document storage. SSE-KMS encrypted. Source of truth for ingestion |
| Observability | LangSmith + Prometheus | Agent decision tracing, query routing visibility |
| Python Tooling | uv | Package management, virtual environments, script running |
| Infrastructure | AWS (EC2, RDS, S3, CloudFront, ALB) | VPC isolation, private subnets, KMS encryption |

## LLM Configuration

The LLM is swappable via three environment variables. **Never hardcode model references.**

```
SSA_LLM_BASE_URL=       # e.g., https://api.mistral.ai/v1 or http://localhost:11434/v1
SSA_LLM_MODEL_NAME=     # e.g., mistral-large-latest or ministral-14b
SSA_LLM_API_KEY=        # API key (empty string for local Ollama)
```

All LLM calls go through a single abstraction layer so swapping providers requires zero code changes.

## Embedding Configuration

The embedding model is swappable via environment variables, same principle as the LLM.

```
SSA_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2  # Dev default (90MB, 384-dim)
SSA_EMBEDDING_DIM=384

# Production:
# SSA_EMBEDDING_MODEL=BAAI/bge-m3  (2.3GB, 1024-dim, multilingual)
# SSA_EMBEDDING_DIM=1024
```

Dev uses a lightweight model because the development machine has 8GB RAM and PyTorch
runs in Docker. The full bge-m3 model (2.3GB) causes OOM in Docker on 8GB machines.
Retrieval quality evaluation happens on AWS with bge-m3 — dev model is for pipeline
testing only, not quality benchmarking.

When switching models: run the Alembic migration to recreate the vector column and HNSW
index with the new dimension, then re-run ingestion or use `backfill_embeddings.py` to
re-embed in batches for memory-constrained environments.

## Project Layout

Two independent uv-managed Python packages plus a frontend:

- `backend/` — FastAPI app, agent (LangGraph), retrieval, LLM client, DB models + migrations
- `ingestion/` — Data ingestion pipeline, source parsers, chunking, embedding
- `frontend/` — React + TypeScript (not yet built)

Key locations:
- DB models (source of truth for schema): `backend/app/db/models.py`
- Migrations: `backend/alembic/versions/`
- Ingestion parsers: `ingestion/pipeline/sources/` (ofac_sdn, ofac_nonsdn, eu_sanctions built)
- Shared upsert logic: `ingestion/pipeline/upsert.py`
- Agent nodes: `backend/app/agent/nodes/`
- Config (env vars): `backend/app/config.py`, `ingestion/pipeline/config.py`

## Agent Pipeline Architecture

Six-node LangGraph pipeline. The two wrapper nodes (preprocess + format) handle the messy human interface so the four core nodes always operate on clean, structured input.

```
User input (potentially mixed DE/EN, typos, compound questions)
  -> preprocess_query    -- normalize language, extract entities, decompose compound queries
    -> classify_query    -- intent routing: entity_lookup | vessel_lookup | guidance_search | regulation_check | hybrid
      -> execute_sql     -- structured entity/vessel lookup (fuzzy matching, relationship traversal)
      -> retrieve_docs   -- ensemble retrieval (BM25 + semantic via pgvector + RRF merge)
      -> [both]          -- hybrid queries run SQL and retrieval in parallel
        -> synthesize    -- merge results from whichever path(s) ran, generate response with inline citations
          -> format_response -- enforce citation format, add data vintage, translate back if source language != EN
            -> User
```

### Node Details

**preprocess_query** — Single LLM call. Output: `{ original_query, normalized_query, entities[], regulations_referenced[], sub_queries[], source_language }`

**classify_query** — Routes to: `entity_lookup | vessel_lookup | guidance_search | regulation_check | hybrid`. Falls back to hybrid if confidence < threshold.

**execute_sql** — Fuzzy name matching via pg_trgm, vessel lookups (IMO/name/owner), relationship traversal for 50% Rule chains. Returns structured results with data_vintage.

**retrieve_docs** — BM25 + semantic search in parallel, merged via Reciprocal Rank Fusion. Metadata filtering by jurisdiction, document_type, date range.

**synthesize** — Merges SQL + retrieval results. Inline citations linking every claim to source. Labels jurisdiction (US/EU/DE). References applicable General Licenses or EU derogations.

**format_response** — Enforces citation format, adds data vintage disclaimers, translates to analyst's source language if needed.

### Conversation Memory

ConversationBufferWindowMemory (window=5). Injected into preprocess_query for coreference resolution across turns.

## Database Schema

All tables are defined in `backend/app/db/models.py` and managed via Alembic migrations. Key design decisions not obvious from the code:

- **Entity type normalization**: OFAC has finer distinctions (organization, government entity, etc.) — we normalize to `individual | entity | vessel | aircraft`. Original sub-type preserved in `raw_record` JSONB.
- **`programs` vs `legal_basis`**: OFAC uses program codes (RUSSIA-EO14024); EU uses regulation references (Reg. 269/2014). Separate arrays because the semantics differ.
- **Vessel names stored separately from entity primary_name**: Vessels get renamed as an evasion tactic — name at designation time may differ from current name.
- **`entity_relationships` for 50% Rule**: Ownership chains are the hardest part of screening. Partial coverage from OFAC remarks + EU XML; RAG supplements with enforcement doc mentions.
- **`document_chunks.embedding` is vector(1024)**: Sized for bge-m3. HNSW index with m=16, ef_construction=64.
- **Generated `tsv` column**: Full-text search via `to_tsvector('english', content)` — BM25-style retrieval.

## Python Environment (uv)

- **Always `uv run`** to execute scripts/tools. Never activate venv manually.
- **Always `uv add`** for dependencies. Never `pip install`.
- **Commit `uv.lock`**, never commit `.venv/`.
- Pin Python version in `.python-version` (currently 3.13).

Quick reference:
```bash
cd backend && uv sync                    # Install deps
cd backend && uv run pytest              # Tests
cd backend && uv run alembic upgrade head # Migrations
cd ingestion && uv run python scripts/ingest_all.py  # Full ingestion
```

## Coding Standards

### Python

- Python 3.13+, async everywhere in backend
- Type hints on all function signatures (`from __future__ import annotations`)
- Pydantic v2 for schemas/settings, SQLAlchemy 2.0 style (`select()`)
- Alembic for all schema changes — never modify DB manually
- Environment variables via `pydantic-settings` with `SSA_` prefix
- Logging via `structlog` (structured JSON, correlation IDs)
- No business logic in route handlers — routes call services, services call repositories

### Linting (ruff)

Config lives in each `pyproject.toml`. Run before commit:
```bash
uv run ruff check . --fix && uv run ruff format .
```
Key rules: no `print()` (use structlog), no `# noqa` without explanation.

### Naming Conventions

- Files: `snake_case.py` | Classes: `PascalCase` | Functions/vars: `snake_case`
- API endpoints: `kebab-case` URLs | DB tables: `snake_case`, plural
- Env vars: `SSA_UPPER_SNAKE_CASE`

### Testing

- pytest + pytest-asyncio, always via `uv run pytest`
- Test structure mirrors source: `test_agent/`, `test_api/`, `test_retrieval/`
- Integration tests use Docker PostgreSQL
- Eval harness in `tests/eval/` (separate from unit tests)

### Git

- Branches: `feature/`, `fix/`, `refactor/`, `docs/`
- Commits: imperative mood, concise

## Key Domain Concepts

- **OFAC SDN List**: ~12,000 entries, pipe-delimited CSV. Primary US sanctions list.
- **EU Consolidated Financial Sanctions List**: ~4,000-6,000 entries, XML format.
- **Reg. 833/2014**: EU sectoral sanctions on Russia (trade, finance, energy). Consolidated version from EUR-Lex.
- **Reg. 269/2014**: EU individual asset freeze designations (equivalent of SDN for specific people/companies).
- **OFAC General Licenses (GLs)**: Authorize specific transactions that would otherwise be blocked.
- **50% Rule**: Entities owned 50%+ by blocked persons are themselves blocked, even if not on SDN.
- **Data vintage**: When source data was fetched. EVERY response must surface this.
- **Vessel designations**: By IMO number. Maritime sanctions (Russia oil price cap) are major analyst workload.
- **Dual-jurisdiction**: European banks in USD markets must comply with BOTH OFAC and EU simultaneously.

## Critical Constraints

1. **Privacy**: Self-hosted mode = zero external API calls. No telemetry, no cloud embeddings.
2. **Source citations**: Every response includes document name, section/article, and data vintage.
3. **LLM portability**: Must work identically on Mistral cloud, Ollama local, or vLLM prod.
4. **Data freshness**: Sanctions data must be <48 hours old in production.
5. **Research assistant only**: Does not access transaction data. Does not make compliance decisions.
6. **Multilingual**: Documents in English and German with EU legal terminology.

## Data Refresh Cadences

| Source | Refresh |
|---|---|
| OFAC SDN / Non-SDN / Vessels | Daily |
| EU Consolidated Financial Sanctions | Daily |
| OFAC General Licenses | Weekly |
| Reg. 833/2014, Reg. 269/2014 | Weekly check, triggered on amendment |
| EU Commission FAQs, OFAC Enforcement/FAQs | Monthly |
| Bundesbank / BaFin Guidance | Quarterly |

Rules: every record carries `data_vintage` + `ingestion_timestamp`. Every API response shows vintage per source. Failures trigger alerts. Source unchanged >3 days = flag potential fetch failure.

## Development Workflow

1. `docker-compose.yml` for PostgreSQL + pgvector (in `backend/`)
2. `cd backend && uv sync` or `cd ingestion && uv sync --extra dev`
3. Backend: `cd backend && uv run uvicorn app.main:app --reload`
4. Migrations: `cd backend && uv run alembic upgrade head`
5. Structured ingestion: `cd ingestion && uv run python scripts/ingest_ofac_sdn.py` (runs natively)
6. Unstructured ingestion (enforcement/guidance PDFs): requires PyTorch for embeddings — use Docker (see `ingestion/README.md`):
   ```bash
   docker build -f ingestion/Dockerfile -t sanctions-ingestion .  # one-time
   docker run --rm --add-host=host.docker.internal:host-gateway \
     -e SSA_DATABASE_URL="postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/sanctions_db" \
     -v $(pwd)/ingestion/data:/app/ingestion/data \
     sanctions-ingestion uv run python scripts/ingest_enforcement.py
   ```
7. Tests: `cd ingestion && uv run pytest` or `cd backend && uv run pytest`
8. Lint: `uv run ruff check . --fix && uv run ruff format .`

### Memory-Constrained Development

The dev machine has 8GB RAM. PyTorch is not compatible with the host OS, so all
embedding work runs in Docker. To avoid OOM during ingestion:

1. Use `all-MiniLM-L6-v2` (90MB) as the dev embedding model, not `bge-m3` (2.3GB)
2. For large document ingestion, use two-pass mode: set `SSA_SKIP_EMBEDDINGS=true`
   to store text chunks first, then run `backfill_embeddings.py` to embed in batches
3. Docker memory limit: `--memory=6g` to leave room for the host OS
4. Batch size for embedding: 25 chunks with MiniLM, 10 chunks with bge-m3

## Common Tasks

### Adding a new data source
1. Create parser in `ingestion/pipeline/sources/` (follow existing pattern)
2. Register in `ingestion/pipeline/runner.py`
3. Add ingestion script in `ingestion/scripts/`

### Modifying the database schema
1. Edit `backend/app/db/models.py`
2. `cd backend && uv run alembic revision --autogenerate -m "description"`
3. Review migration, then `uv run alembic upgrade head`

### Adding a new agent node
1. Node in `backend/app/agent/nodes/`
2. Routing in `backend/app/agent/graph.py`
3. Prompt in `backend/app/agent/prompts/`
4. Update classify_query to recognize new intent
