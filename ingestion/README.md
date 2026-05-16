# Ingestion Pipeline

Downloads, parses, and loads sanctions data into PostgreSQL. Two types of data:

- **Structured data** (OFAC SDN, Non-SDN, EU Consolidated List) — parsed into `sanctioned_entities` and related tables
- **Unstructured data** (enforcement PDFs, guidance docs) — extracted, chunked, embedded, and stored in `document_chunks` for RAG retrieval

## What's Inside

| Directory/File | Purpose |
| -------------- | ------- |
| `pipeline/sources/` | One parser per data source (see [sources/README.md](pipeline/sources/README.md) for sanctions domain context) |
| `pipeline/runner.py` | Orchestrator: runs registered sources with hash-based change detection |
| `pipeline/upsert.py` | Shared INSERT ON CONFLICT logic for structured entity parsers |
| `pipeline/chunk_store.py` | Full-replace storage for document chunks (unstructured pipeline) |
| `pipeline/embeddings.py` | Embedding model wrapper (BAAI/bge-m3, lazy-loaded) |
| `pipeline/extraction.py` | PDF text extraction (PyMuPDF + Tesseract OCR fallback) |
| `pipeline/chunking/text_chunker.py` | RecursiveCharacterTextSplitter wrapper (~500 tokens, ~50 token overlap) |
| `pipeline/loaders.py` | HTTP download with retry, S3 client wrapper |
| `pipeline/hashing.py` | SHA-256 hash functions and persistent HashStore |
| `pipeline/models.py` | `IngestionResult` and `AcquisitionResult` Pydantic models |
| `pipeline/config.py` | pydantic-settings configuration (`SSA_` prefix) |
| `pipeline/db.py` | Async session factory (reads from config) |
| `pipeline/db_models.py` | Re-exports all SQLAlchemy models from `backend/app/db/models.py` |
| `pipeline/exceptions.py` | `IngestionError` and `RecordParseError` |
| `scripts/` | CLI entry points for running ingestion |
| `tests/` | 274 unit tests covering all parsing and pipeline logic |

## Registered Sources

| Source | Type | Script | Data |
| ------ | ---- | ------ | ---- |
| `ofac_sdn` | Structured | `scripts/ingest_ofac_sdn.py` | OFAC SDN list (~19k entities) |
| `ofac_nonsdn` | Structured | `scripts/ingest_ofac_nonsdn.py` | OFAC Non-SDN list (~440 entities) |
| `eu_consolidated` | Structured | `scripts/ingest_eu_sanctions.py` | EU Consolidated Financial Sanctions (~6k entities) |
| `enforcement` | Unstructured | `scripts/ingest_enforcement.py` | 20 OFAC enforcement PDFs (auto-downloaded) |
| `guidance` | Unstructured | `scripts/ingest_guidance.py` | OFAC Compliance Framework + 50% Rule guidance |

## Running

### Structured sources (no GPU/PyTorch needed)

Structured parsers (OFAC SDN, Non-SDN, EU) run natively on any platform:

```bash
uv sync --extra dev

# Full ingestion (all registered sources — but see below for unstructured)
uv run python scripts/ingest_all.py

# Single source
uv run python scripts/ingest_ofac_sdn.py
uv run python scripts/ingest_ofac_nonsdn.py
uv run python scripts/ingest_eu_sanctions.py

# Incremental (skip sources whose files haven't changed)
uv run python scripts/ingest_incremental.py
```

### Unstructured sources (requires PyTorch via Docker)

Enforcement and guidance ingestion requires `sentence-transformers` + PyTorch to generate
embeddings for the document chunks. PyTorch does not have wheels for all platforms (notably
macOS x86_64 + Python 3.13). **Use the Docker image to run these sources.**

#### Why Docker?

The embedding model (BAAI/bge-m3) runs on `sentence-transformers`, which depends on PyTorch.
PyTorch only publishes wheels for Linux (x86_64, aarch64), macOS ARM (Apple Silicon), and
Windows. If you're on an unsupported platform (e.g., macOS Intel), the Docker image provides
a Linux environment where PyTorch installs normally.

On Linux or macOS ARM, you can run unstructured ingestion natively with `uv sync --extra embeddings`.

#### Build the image (one-time)

From the project root (`sanctioner-app/`):

```bash
docker build -f ingestion/Dockerfile -t sanctions-ingestion .
```

This installs all dependencies including PyTorch and sentence-transformers (~4GB image).
The build takes 5-10 minutes the first time.

#### Run ingestion

The container connects to your host's PostgreSQL via `host.docker.internal`. The `data/`
volume mount persists downloaded PDFs so they aren't re-downloaded on subsequent runs.

```bash
# Enforcement PDFs (20 OFAC settlement agreements)
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e SSA_DATABASE_URL="postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/sanctions_db" \
  -v $(pwd)/ingestion/data:/app/ingestion/data \
  sanctions-ingestion \
  uv run python scripts/ingest_enforcement.py

# Guidance documents (OFAC Compliance Framework + 50% Rule)
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e SSA_DATABASE_URL="postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/sanctions_db" \
  -v $(pwd)/ingestion/data:/app/ingestion/data \
  sanctions-ingestion \
  uv run python scripts/ingest_guidance.py

# Or run all sources at once
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e SSA_DATABASE_URL="postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/sanctions_db" \
  -v $(pwd)/ingestion/data:/app/ingestion/data \
  sanctions-ingestion \
  uv run python scripts/ingest_all.py
```

The first run downloads the bge-m3 embedding model (~2.3GB) which is cached inside the
container's Hugging Face cache. To persist the model cache across runs, add:

```bash
-v $(pwd)/.hf_cache:/root/.cache/huggingface
```

### Tests

Tests mock all external dependencies (PyTorch, downloads, database) and run natively:

```bash
uv sync --extra dev
uv run pytest
```

## Data Directory Layout

Source data files live in `data/` (configurable via `SSA_DATA_DIR`). Structured sources
require manual file placement; unstructured sources auto-download from OFAC:

```
data/
├── ofac_sdn/          # sdn.csv, add.csv, alt.csv, sdn_comments.csv
├── ofac_nonsdn/       # cons_prim.csv, cons_add.csv, cons_alt.csv, cons_comments.csv
├── eu_consolidated/   # *.xml (EU Consolidated Financial Sanctions List)
├── enforcement/       # Auto-downloaded: 20 OFAC enforcement action PDFs
└── guidance/          # Auto-downloaded: OFAC Compliance Framework, 50% Rule
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
