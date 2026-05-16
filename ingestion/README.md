# Ingestion Pipeline

Downloads, parses, and loads sanctions data into PostgreSQL. Handles OFAC SDN/Non-SDN lists and the EU Consolidated Financial Sanctions List. Each source has a dedicated parser that normalizes records into a standard format before upserting to the database.

## What's Inside

| Directory/File | Purpose |
| -------------- | ------- |
| `pipeline/sources/` | One parser per data source (see [sources/README.md](pipeline/sources/README.md) for sanctions domain context, field coverage stats, and compliance use cases) |
| `pipeline/runner.py` | Orchestrator: runs registered sources with hash-based change detection |
| `pipeline/upsert.py` | Shared INSERT ON CONFLICT logic for all entity parsers |
| `pipeline/loaders.py` | HTTP download with retry, S3 client wrapper |
| `pipeline/hashing.py` | SHA-256 hash functions and persistent HashStore |
| `pipeline/models.py` | `IngestionResult` and `AcquisitionResult` Pydantic models |
| `pipeline/config.py` | pydantic-settings configuration (`SSA_` prefix) |
| `pipeline/db.py` | Async session factory (reads from config) |
| `pipeline/db_models.py` | Re-exports all SQLAlchemy models from `backend/app/db/models.py` |
| `pipeline/exceptions.py` | `IngestionError` and `RecordParseError` |
| `scripts/` | CLI entry points for running ingestion |
| `tests/` | 110 unit tests covering all parsing logic |

## Running

```bash
uv sync

# Full ingestion (all registered sources)
uv run python scripts/ingest_all.py

# Single source
uv run python scripts/ingest_ofac_sdn.py
uv run python scripts/ingest_ofac_nonsdn.py
uv run python scripts/ingest_eu_sanctions.py

# Incremental (skip sources whose files haven't changed)
uv run python scripts/ingest_incremental.py

# Tests
uv run pytest
```

## Data Directory Layout

Source data files must be placed in `data/` (configurable via `SSA_DATA_DIR`):

```
data/
├── ofac_sdn/          # sdn.csv, add.csv, alt.csv, sdn_comments.csv
├── ofac_nonsdn/       # cons_prim.csv, cons_add.csv, cons_alt.csv, cons_comments.csv
└── eu_consolidated/   # *.xml (EU Consolidated Financial Sanctions List)
```

## How It Works

`runner.py` iterates over `REGISTERED_SOURCES`, computes a SHA-256 hash of each source's data files, and skips sources that haven't changed since the last run (hash stored in `data/.ingestion_hashes.json`). For each changed source, it opens a database session and calls the source's parser function. The parser reads files, normalizes records, and calls `upsert_entities()` to write to PostgreSQL. Every run is logged to the `ingestion_log` table.

## Dependencies

- Depends on: `backend/app/db/models.py` (path dependency in pyproject.toml), PostgreSQL
- Depended on by: nothing (standalone pipeline, run from CLI scripts)

## Key Decisions

- **Single source of truth for models.** `db_models.py` re-exports from the backend package rather than defining its own models, preventing schema drift between the two packages.
- **Hash-based change detection.** `HashStore` persists file hashes to skip re-ingestion when source data hasn't changed. This makes `ingest_all.py` safe to run repeatedly.
- **Shared upsert function.** All parsers use `upsert.py` instead of writing their own INSERT/UPDATE logic. This ensures consistent conflict resolution, child record handling, and removal tracking.
