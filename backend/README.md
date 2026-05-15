# Backend

FastAPI application serving the sanctions screening assistant API. Async throughout (SQLAlchemy async, httpx, asyncpg). Currently in Phase 1: database layer and health endpoint are implemented; the agent pipeline, retrieval, LLM client, and API routes are scaffolded for Phase 2.

## What's Inside

| Directory/File | Purpose |
| -------------- | ------- |
| `app/main.py` | FastAPI entry point with `/health` endpoint |
| `app/config.py` | pydantic-settings configuration (`SSA_` env prefix) |
| `app/exceptions.py` | Domain exception hierarchy (5 exception types) |
| `app/logging.py` | structlog setup with JSON rendering |
| `app/db/` | SQLAlchemy models, async session factory, migrations |
| `app/api/` | API routes and Pydantic schemas (scaffolded) |
| `app/agent/` | LangGraph pipeline nodes and prompts (scaffolded) |
| `app/retrieval/` | Embedding, vector search, BM25, ensemble (scaffolded) |
| `app/llm/` | LLM client abstraction (scaffolded) |
| `alembic/` | Database migration files |
| `tests/` | Test suite |
| `docker-compose.yml` | Local PostgreSQL 16 + pgvector |

## Running

```bash
uv sync
docker compose up -d                            # Start PostgreSQL
uv run alembic upgrade head                     # Apply migrations
uv run uvicorn app.main:app --reload            # Start dev server
uv run pytest                                   # Run tests
uv run ruff check . --fix && uv run ruff format . # Lint + format
```

## Dependencies

- Depends on: PostgreSQL 16 + pgvector (via docker-compose.yml)
- Depended on by: `ingestion/` (imports `app.db.models` as path dependency)

## Key Decisions

- **Single database for structured data + vectors.** PostgreSQL with pgvector handles both entity tables and embedding search, avoiding a separate vector database. Keeps the deployment simple and lets SQL joins cross both worlds.
- **Async session factory at module level.** `session.py` creates the engine and session factory at import time from `settings.database_url`. FastAPI dependency injection yields sessions per-request.
- **Raw record preservation.** Every `SanctionedEntity` stores the original source record as JSONB in `raw_record` for audit and future field extraction without re-ingestion.
