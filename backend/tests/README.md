# Backend Tests

pytest test suite for the backend application. Currently covers the health endpoint. Test directories for agent, API, and retrieval are scaffolded for Phase 2.

## What's Inside

| File/Directory | Purpose |
| -------------- | ------- |
| `conftest.py` | Shared fixtures: httpx `AsyncClient` via `ASGITransport` |
| `test_api/test_health.py` | Health endpoint tests (2 tests) |
| `test_api/` | API route tests |
| `test_agent/` | Agent pipeline tests (scaffolded) |
| `test_retrieval/` | Retrieval pipeline tests (scaffolded) |

## Running

```bash
cd backend
uv run pytest              # All tests
uv run pytest -v           # Verbose output
uv run pytest test_api/    # Specific directory
```

## How It Works

Tests use `pytest-asyncio` for async test support and `httpx.AsyncClient` with `ASGITransport` to test FastAPI endpoints without starting a server. The `client` fixture in `conftest.py` provides a pre-configured async HTTP client.

Integration tests requiring PostgreSQL will use testcontainers (already a dev dependency). Each test directory can have its own `conftest.py` for directory-specific fixtures.

## Dependencies

- Depends on: `app.main` (FastAPI app instance), `pytest`, `pytest-asyncio`, `httpx`

## Adding Tests

1. Place test files in the matching `test_*/` directory (mirrors `app/` structure)
2. Name test files `test_*.py` and test functions `test_*`
3. Use the `client` fixture from `conftest.py` for HTTP endpoint tests
4. Async tests are detected automatically by `pytest-asyncio`
