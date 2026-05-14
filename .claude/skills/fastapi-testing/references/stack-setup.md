# Approved Testing Stack & Setup

## The Stack (use exactly this — do not substitute)

| Tool | Purpose | Why |
|------|---------|-----|
| `pytest` | Test runner | Standard, extensible |
| `pytest-asyncio` | Async test support | Native async without wrappers |
| `httpx` + `AsyncClient` | Endpoint testing | Tests real async paths, not sync wrappers |
| `testcontainers` | Real PostgreSQL + pgvector in tests | Catches DB-specific bugs SQLite misses |
| `pytest-cov` | Coverage reporting | CI integration |

**Do NOT use:**
- `TestClient` (sync wrapper, misses async bugs)
- SQLite as a test database (masks PostgreSQL-specific behavior, no pgvector support)
- `unittest.mock.patch` for the database (use `dependency_overrides` instead)

---

## Dependencies to Add

```toml
# pyproject.toml — add to dev dependencies
[tool.uv.dev-dependencies]
pytest = ">=8.0"
pytest-asyncio = ">=0.23"
pytest-cov = ">=4.0"
httpx = ">=0.27"
testcontainers = {extras = ["postgres"], version = ">=4.0"}
```

Install with:
```bash
uv add --dev pytest pytest-asyncio pytest-cov httpx "testcontainers[postgres]"
```

---

## pytest Configuration

```ini
# pytest.ini (create in backend/ root)
[pytest]
asyncio_mode = auto
testpaths = tests
```

`asyncio_mode = auto` means you never need `@pytest.mark.asyncio` on individual tests.
Every `async def test_*` runs automatically as async.

---

## Project Test Structure

```
backend/tests/
├── conftest.py              # Shared fixtures: db, app, async client
├── test_agent/
│   ├── test_preprocess.py
│   ├── test_classify.py
│   ├── test_sql_lookup.py
│   ├── test_retrieve.py
│   ├── test_synthesize.py
│   └── test_format_response.py
├── test_api/
│   ├── test_query.py
│   ├── test_entity.py
│   └── test_stream.py
├── test_retrieval/
│   ├── test_embeddings.py
│   ├── test_vector_store.py
│   ├── test_bm25.py
│   └── test_ensemble.py
└── eval/
    ├── eval_queries.json
    └── run_eval.py
```

---

## Core Fixtures (`backend/tests/conftest.py`)

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from app.main import app
from app.db.session import get_async_session
from app.db.models import Base


# ── Database fixture (real PostgreSQL via Docker) ──────────────────────────

@pytest.fixture(scope="session")
def postgres_container():
    """Spin up a real PostgreSQL + pgvector container for the test session."""
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        yield postgres


@pytest.fixture(scope="session")
async def test_engine(postgres_container):
    """Create async engine pointing at the test container."""
    url = postgres_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncSession:
    """Provide a clean DB session per test, rolled back after each test."""
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ── App fixture with dependency override ──────────────────────────────────

@pytest.fixture
async def client(db_session) -> AsyncClient:
    """AsyncClient with DB overridden to use test session."""
    app.dependency_overrides[get_async_session] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────

@pytest.fixture
async def test_entity(db_session) -> dict:
    """Create a minimal sanctioned entity for tests that need one."""
    from app.db.models import SanctionedEntity
    import uuid
    from datetime import datetime, timezone

    entity = SanctionedEntity(
        id=uuid.uuid4(),
        source="ofac_sdn",
        source_id="12345",
        entity_type="entity",
        primary_name="Test Bank LLC",
        programs=["RUSSIA-EO14024"],
        legal_basis=[],
        last_updated=datetime.now(timezone.utc),
        data_vintage=datetime.now(timezone.utc),
    )
    db_session.add(entity)
    await db_session.flush()
    return entity


@pytest.fixture
async def test_vessel(db_session, test_entity) -> dict:
    """Create a vessel record linked to a sanctioned entity."""
    from app.db.models import Vessel
    import uuid

    vessel = Vessel(
        id=uuid.uuid4(),
        entity_id=test_entity.id,
        vessel_name="TEST VESSEL",
        imo_number="1234567",
        vessel_type="Crude Oil Tanker",
        flag="Panama",
    )
    db_session.add(vessel)
    await db_session.flush()
    return vessel
```

---

## Running Tests

```bash
# Run all tests
cd backend && uv run pytest

# Run with coverage report
uv run pytest --cov=app --cov-report=term-missing

# Run a specific layer
uv run pytest tests/test_agent/
uv run pytest tests/test_api/
uv run pytest tests/test_retrieval/

# Run a single file
uv run pytest tests/test_agent/test_classify.py -v

# Skip slow integration tests during development
uv run pytest -m "not integration" -v
```
