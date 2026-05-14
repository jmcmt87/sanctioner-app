---
name: sqlalchemy-alembic-patterns
description: >
  Use this skill whenever creating, modifying, or reviewing SQLAlchemy models, Alembic
  migrations, database repositories, or session management. Triggers on: defining a new
  table, adding a column, creating a migration, writing a repository method, setting up
  the async session factory, or any work touching backend/app/db/. Also trigger when
  the user asks about pgvector indexes, HNSW configuration, full-text search setup,
  or database query patterns.
---

# SQLAlchemy + Alembic Patterns

This skill defines the exact conventions for all database code in the Sanctions Screening
Assistant. The database is PostgreSQL 16 + pgvector. All access is async.

---

## Model Conventions

### Base Setup

```python
# backend/app/db/models.py
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    Date,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass
```

### Column Patterns

**Every model uses these patterns — no exceptions:**

```python
# UUID primary key — always server-side default
id: Mapped[uuid.UUID] = mapped_column(
    primary_key=True,
    server_default=func.gen_random_uuid(),
)

# Timestamps — always timezone-aware
last_updated: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
data_vintage: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
ingestion_timestamp: Mapped[datetime] = mapped_column(
    TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
)

# Text fields
primary_name: Mapped[str] = mapped_column(Text, nullable=False)
remarks: Mapped[str | None] = mapped_column(Text)

# Array columns (programs, nationality, legal_basis)
programs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
nationality: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
legal_basis: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

# JSONB columns
raw_record: Mapped[dict | None] = mapped_column(JSONB)
metadata: Mapped[dict | None] = mapped_column(JSONB)

# Date columns
date_of_birth: Mapped[date | None] = mapped_column(Date)
list_date: Mapped[date | None] = mapped_column(Date)
published_date: Mapped[date | None] = mapped_column(Date)

# Integer columns
chunk_index: Mapped[int | None] = mapped_column(Integer)
build_year: Mapped[int | None] = mapped_column(Integer)

# Numeric columns (for ownership percentage)
ownership_percentage: Mapped[float | None] = mapped_column(Numeric)

# pgvector column — dimension must match embedding model (1024 for bge-m3)
embedding: Mapped[list | None] = mapped_column(Vector(1024))

# Foreign keys — always named {referenced_table_singular}_id
entity_id: Mapped[uuid.UUID] = mapped_column(
    ForeignKey("sanctioned_entities.id", ondelete="CASCADE"), nullable=False
)
```

### Relationship Patterns

**Always use `relationship()` with explicit `back_populates`. Never use `backref`.**

```python
# In SanctionedEntity model
aliases: Mapped[list[EntityAlias]] = relationship(
    back_populates="entity", cascade="all, delete-orphan"
)
vessels: Mapped[list[Vessel]] = relationship(
    back_populates="entity", cascade="all, delete-orphan"
)
addresses: Mapped[list[EntityAddress]] = relationship(
    back_populates="entity", cascade="all, delete-orphan"
)
identifiers: Mapped[list[EntityIdentifier]] = relationship(
    back_populates="entity", cascade="all, delete-orphan"
)

# In EntityAlias model
entity: Mapped[SanctionedEntity] = relationship(back_populates="aliases")
```

### Unique Constraints

```python
# On SanctionedEntity — prevents duplicate entries from same source
__table_args__ = (
    UniqueConstraint("source", "source_id", name="uq_sanctioned_entities_source_source_id"),
)

# On EntityRelationship — prevents duplicate relationships
__table_args__ = (
    UniqueConstraint(
        "from_entity_id", "to_entity_id", "relationship_type",
        name="uq_entity_relationships_from_to_type",
    ),
)
```

### Naming Conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Table names | Plural, snake_case | `sanctioned_entities`, `entity_aliases` |
| Column names | snake_case | `primary_name`, `data_vintage` |
| Foreign keys | `{singular_table}_id` | `entity_id`, `from_entity_id` |
| Unique constraints | `uq_{table}_{columns}` | `uq_sanctioned_entities_source_source_id` |
| Indexes | `ix_{table}_{columns}` | `ix_document_chunks_jurisdiction` |
| HNSW index | `ix_{table}_embedding_hnsw` | `ix_document_chunks_embedding_hnsw` |
| GIN index | `ix_{table}_tsv_gin` | `ix_document_chunks_tsv_gin` |

---

## Index Setup

### pgvector HNSW Index

```sql
-- For vector similarity search on document_chunks
CREATE INDEX ix_document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

**Important**: Alembic autogenerate will NOT create this index. You must add it manually
to the migration file:

```python
# In migration file
from alembic import op

def upgrade():
    # ... autogenerated table creation ...

    # Manual: HNSW index for vector similarity search
    op.execute("""
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    # ... autogenerated drops ...
```

### Full-Text Search (GIN Index + Generated Column)

```sql
-- Generated tsvector column for BM25-style retrieval
ALTER TABLE document_chunks ADD COLUMN tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

CREATE INDEX ix_document_chunks_tsv_gin ON document_chunks USING gin (tsv);
```

**Also manual in migration**. Autogenerate won't handle generated columns or GIN indexes:

```python
def upgrade():
    # Manual: full-text search generated column + GIN index
    op.execute("""
        ALTER TABLE document_chunks ADD COLUMN tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    """)
    op.execute("""
        CREATE INDEX ix_document_chunks_tsv_gin
        ON document_chunks USING gin (tsv)
    """)
```

### Trigram Index (for fuzzy entity name matching)

```sql
-- Enable pg_trgm extension
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- GIN trigram index on primary_name for fuzzy search
CREATE INDEX ix_sanctioned_entities_primary_name_trgm
    ON sanctioned_entities USING gin (primary_name gin_trgm_ops);

-- Also on alias_name
CREATE INDEX ix_entity_aliases_alias_name_trgm
    ON entity_aliases USING gin (alias_name gin_trgm_ops);
```

---

## Session Management

### Async Session Factory

```python
# backend/app/db/session.py
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

engine = create_async_engine(
    settings.ssa_database_url,
    echo=False,  # Set True for SQL debugging, never in production
    pool_size=5,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

### Dependency Injection

```python
# backend/app/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.db.repositories.entity_repository import EntityRepository
from app.db.repositories.chunk_repository import ChunkRepository


async def get_entity_repository(
    session: AsyncSession = Depends(get_async_session),
) -> EntityRepository:
    return EntityRepository(session)


async def get_chunk_repository(
    session: AsyncSession = Depends(get_async_session),
) -> ChunkRepository:
    return ChunkRepository(session)
```

**Rules:**
- Repositories NEVER create their own sessions. They receive sessions via DI.
- No manual `session.begin()` / `session.commit()` in route handlers. Use the session
  context manager or let FastAPI handle it via the dependency lifecycle.
- The ingestion pipeline (which runs outside FastAPI) creates sessions directly from
  `async_session_factory` — this is the one exception to the DI rule.

---

## Repository Pattern

One repository class per domain. Repositories contain all database queries for that domain.

```python
# backend/app/db/repositories/entity_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SanctionedEntity, EntityAlias


class EntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> SanctionedEntity | None:
        return await self.session.get(SanctionedEntity, entity_id)

    async def search_by_name(
        self,
        name: str,
        jurisdiction: str | None = None,
        limit: int = 20,
    ) -> list[SanctionedEntity]:
        stmt = (
            select(SanctionedEntity)
            .where(SanctionedEntity.primary_name.ilike(f"%{name}%"))
        )
        if jurisdiction:
            # Filter by source prefix for jurisdiction
            stmt = stmt.where(SanctionedEntity.source.startswith(jurisdiction.lower()))
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def fuzzy_search(
        self,
        name: str,
        threshold: float = 0.3,
        limit: int = 20,
    ) -> list[SanctionedEntity]:
        """Fuzzy name search using pg_trgm similarity."""
        stmt = (
            select(SanctionedEntity)
            .where(func.similarity(SanctionedEntity.primary_name, name) > threshold)
            .order_by(func.similarity(SanctionedEntity.primary_name, name).desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

**Rules:**
- Always use `select()` — never legacy `session.query()`.
- Always return typed results, not raw rows.
- Never put business logic in repositories. They fetch and store data. That's it.
- Repositories don't know about HTTP, agents, or LLMs.

---

## Alembic Migration Conventions

### Generating a Migration

```bash
cd backend
uv run alembic revision --autogenerate -m "Add entity_relationships table"
```

### Migration Message Format
Imperative mood, concise. Describes what the migration does, not why.
- Good: `"Add entity_relationships table"`
- Good: `"Add nationality column to sanctioned_entities"`
- Good: `"Create HNSW index on document_chunks embedding"`
- Bad: `"Updated the schema for the new feature"`
- Bad: `"Fixed the entities table"`

### Always Review Autogenerated Migrations

Autogenerate gets wrong or misses:
- **Column renames** — it generates DROP + ADD instead of ALTER. Fix manually.
- **pgvector indexes** (HNSW, IVFFlat) — not detected. Add manually.
- **GIN indexes** — sometimes missed. Verify and add manually.
- **Generated columns** (tsvector) — not supported by autogenerate. Add manually.
- **Custom index parameters** (m, ef_construction) — not supported. Add manually.
- **Extension creation** (pgvector, pg_trgm) — add manually.

### Extension Setup Migration

The first migration should enable required extensions:

```python
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")    # pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")   # trigram similarity
```

### Rules
- **Never edit a migration after it's been applied.** Create a new one.
- **One migration per logical change.** Don't bundle unrelated schema changes.
- **Always test migrations against a fresh database**: `alembic downgrade base && alembic upgrade head`.
- **Commit migration files to git** alongside the model changes that require them.
