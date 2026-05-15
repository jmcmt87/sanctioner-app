# Database Layer

SQLAlchemy ORM models and async session management for the sanctions screening database. PostgreSQL 16 with pgvector provides both structured entity storage and vector similarity search in a single database.

## What's Inside

| File | Purpose |
| ---- | ------- |
| `models.py` | 8 SQLAlchemy 2.0 ORM models matching the constitutional schema |
| `session.py` | Async engine and session factory (asyncpg, pool_size=5) |
| `repositories/` | Data access layer, one file per domain (scaffolded) |

## How It Works

`models.py` defines the complete data model: `SanctionedEntity` is the core table with child tables for aliases, addresses, identifiers, vessels, and inter-entity relationships. `DocumentChunk` stores RAG content with pgvector embeddings (1024-dim for bge-m3). `IngestionLog` tracks every pipeline run.

`session.py` creates an async engine and `async_sessionmaker` at import time. The `get_async_session()` generator is designed for FastAPI dependency injection.

Schema changes go through Alembic migrations in `backend/alembic/`. Two migrations exist: one for PostgreSQL extensions (pgvector, pg_trgm) and one for all tables plus HNSW, GIN, and trigram indexes. See [CLAUDE.md](../../../CLAUDE.md) for the full schema documentation.

## Dependencies

- Depends on: `app.config` (database URL)
- Depended on by: `ingestion.pipeline.db_models` (re-exports all models), `app.api` and `app.agent` (future)

## Key Decisions

- **`metadata_` attribute maps to `metadata` column on DocumentChunk.** SQLAlchemy reserves the name `metadata` on `DeclarativeBase`, so the Python attribute is `metadata_` with an explicit column name mapping.
- **Entity type normalization.** OFAC uses finer distinctions (organization, government entity, etc.) but we normalize to four types: `individual`, `entity`, `vessel`, `aircraft`. The original sub-type is preserved in `raw_record` JSONB.
- **TEXT columns instead of ENUMs for source, entity_type, jurisdiction.** New values can be added without database migrations.

## Modifying the Schema

1. Edit models in `models.py`
2. Generate migration: `uv run alembic revision --autogenerate -m "description"`
3. Review the generated migration in `alembic/versions/`
4. Apply: `uv run alembic upgrade head`
