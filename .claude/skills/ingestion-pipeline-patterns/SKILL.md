---
name: ingestion-pipeline-patterns
description: >
  Use this skill whenever building, modifying, or adding a data source parser in the
  ingestion pipeline (ingestion/pipeline/sources/). Triggers on: creating a new source
  parser, modifying an existing parser, adding a new data source, building the pipeline
  runner, implementing incremental update logic, or any work touching the ingestion/
  directory. This skill ensures every data source follows the same structural pattern
  so parsers built in week 1 look identical to parsers built in week 6.
---

# Ingestion Pipeline Patterns

Every data source in this project follows the same six-step pattern. No exceptions.
When the Builder references "how should I structure the parser," this is the answer.

---

## The Six-Step Ingestion Pattern

Every source parser in `ingestion/pipeline/sources/` implements these steps in order:

### Step 1 — Download
Fetch the source file from S3. If the file hasn't been acquired yet, download from origin
first (see the data-acquisition-patterns skill) and upload to S3.

- Log the fetch timestamp.
- The S3 path is the source of truth: `raw/{category}/{source_name}/{YYYY-MM-DD}/{filename}`.
- If the file hasn't changed since the last run (compare hashes), short-circuit and return
  an IngestionResult with `records_processed=0` and `status='skipped_unchanged'`.

### Step 2 — Parse
Transform the raw format into an intermediate Python representation.

- CSV (OFAC SDN): Parse pipe-delimited CSV into a list of dicts or Pydantic models.
- XML (EU Consolidated List): Parse XML into a list of dicts or Pydantic models.
- PDF (enforcement actions, guidance): Extract text via a PDF library, then chunk.
- HTML (OFAC FAQs, EUR-Lex regulations): Parse with BeautifulSoup, extract structured content.

This step is source-specific. Each source has different raw formats and different parsing logic.
The output is always a uniform intermediate representation — a list of parsed records.

### Step 3 — Validate
Check that required fields are present and types are correct.

- **Structured entities** must have: `source`, `source_id`, `entity_type`, `primary_name`.
- **Document chunks** must have: `content` (non-empty), `source_document`, `jurisdiction`, `document_type`.
- Invalid records are **logged and skipped**, never crash the pipeline. Use structlog:
  ```python
  logger.warning("skipping_invalid_record", source=source_name, record_id=record_id, reason="missing primary_name")
  ```
- Track the count of skipped records for the ingestion log.

### Step 4 — Map
Transform the intermediate representation into database-ready objects.

- **Structured data** → SQLAlchemy model instances (`SanctionedEntity`, `Vessel`, `EntityAlias`, etc.)
- **Unstructured data** → `DocumentChunk` records with embeddings generated via the embedding wrapper.

Every mapped record must carry these metadata fields — no exceptions:

**Structured entities:**
| Field | Source | Required |
|-------|--------|----------|
| `source` | Hardcoded per parser (e.g., `'ofac_sdn'`, `'eu_consolidated'`) | Yes |
| `source_id` | From the raw data (OFAC entry_id, EU entity reference) | Yes |
| `data_vintage` | Timestamp of the source data itself (e.g., OFAC "last updated" date) | Yes |
| `last_updated` | Current timestamp (when this record was written to DB) | Yes |
| `raw_record` | Full original record as JSONB — preserves everything for audit | Yes |

**Document chunks:**
| Field | Source | Required |
|-------|--------|----------|
| `source_document` | S3 key or document identifier | Yes |
| `source_title` | Document title (human-readable) | Yes |
| `jurisdiction` | `'US'`, `'EU'`, or `'DE'` | Yes |
| `document_type` | `'enforcement'`, `'regulation'`, `'guidance'`, `'faq'`, `'general_license'` | Yes |
| `article_reference` | For regulations: `'Article 5b(1)'`. Null for other doc types. | When applicable |
| `published_date` | Original publication date of the document | Yes |
| `chunk_index` | Position within document (0-indexed) | Yes |
| `ingestion_timestamp` | Current timestamp | Yes |
| `data_vintage` | When the source document was fetched | Yes |

### Step 5 — Upsert / Store
Write to PostgreSQL.

**For structured data (entities, vessels, aliases):**
- Upsert by `(source, source_id)` — the UNIQUE constraint on `sanctioned_entities`.
- On conflict, update all mutable fields (programs, legal_basis, remarks, data_vintage, last_updated, raw_record).
- For related tables (aliases, addresses, identifiers): delete existing children and re-insert.
  This is simpler and safer than diffing individual alias records.
- Track counts: `records_added`, `records_updated`, `records_removed`.

**For unstructured data (document chunks):**
- On re-ingestion of a document: delete all existing chunks for that `source_document`, then insert new chunks.
  This is a full-replace strategy — simpler than chunk-level diffing and guarantees consistency.
- For first-time ingestion: straight insert.

**For incremental updates (SDN list, EU list):**
- Compare incoming records against existing records using a hash of key fields.
- Categories: new records (insert), modified records (update), removed records (mark as removed or delete,
  depending on policy — for MVP, delete and log).
- The hash comparison must be deterministic: sort fields, normalize whitespace, use a stable serialization.

### Step 6 — Log
Write to the `ingestion_log` table. Every run, whether successful or not.

```python
IngestionLog(
    source="ofac_sdn",
    ingestion_type="full",          # or "incremental"
    started_at=start_time,
    completed_at=end_time,
    records_processed=total,
    records_added=added,
    records_updated=updated,
    records_removed=removed,
    status="completed",             # or "completed_with_errors" or "failed"
    error_message=None,             # or error details
    source_vintage=source_date,     # the date of the SOURCE data, not the fetch time
)
```

**Status values:**
- `completed` — all records processed successfully.
- `completed_with_errors` — some records skipped due to parse/validation errors. The pipeline finished.
- `failed` — infrastructure failure (DB down, S3 unreachable). The pipeline did not finish.
- `skipped_unchanged` — source file hash unchanged since last run. No processing needed.

---

## Error Handling Rules

1. **Individual record failures** → log and skip. Do not abort the batch.
   ```python
   for record in parsed_records:
       try:
           mapped = map_to_entity(record)
           batch.append(mapped)
       except ValidationError as e:
           skipped += 1
           logger.warning("record_validation_failed", source=source_name, error=str(e))
   ```

2. **Infrastructure failures** (DB connection lost, S3 unreachable) → catch at the top level,
   log to ingestion_log with `status='failed'`, re-raise so the caller knows.

3. **Never silently swallow errors.** Every exception is either handled (logged + skipped) or propagated.

---

## File Structure Convention

```
ingestion/
├── pipeline/
│   ├── __init__.py
│   ├── runner.py                    # Orchestrator — runs one or all sources
│   ├── models.py                    # IngestionResult, AcquisitionResult Pydantic models
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── ofac_sdn.py             # ingest_ofac_sdn(session, s3_client, config) -> IngestionResult
│   │   ├── ofac_nonsdn.py          # ingest_ofac_nonsdn(...)
│   │   ├── ofac_vessels.py         # ingest_ofac_vessels(...)
│   │   ├── eu_sanctions.py         # ingest_eu_sanctions(...)
│   │   ├── enforcement.py          # ingest_enforcement_actions(...)
│   │   └── guidance.py             # ingest_guidance_docs(...)
│   ├── chunking/
│   │   ├── text_chunker.py         # RecursiveCharacterTextSplitter wrapper
│   │   └── regulation_chunker.py   # Structure-aware chunker for legal texts
│   ├── embeddings.py               # Batch embedding generation wrapper
│   └── loaders.py                  # S3 download + local file helpers
```

**Each source file exports a single async function:**
```python
async def ingest_ofac_sdn(
    session: AsyncSession,
    s3_client: S3Client,
    config: IngestionConfig,
) -> IngestionResult:
    """Ingest OFAC SDN list from S3 into sanctioned_entities table."""
    ...
```

**The runner registers all sources:**
```python
# ingestion/pipeline/runner.py
REGISTERED_SOURCES: dict[str, SourceHandler] = {
    "ofac_sdn": ingest_ofac_sdn,
    "ofac_nonsdn": ingest_ofac_nonsdn,
    "eu_consolidated": ingest_eu_sanctions,
    "enforcement": ingest_enforcement_actions,
    "guidance": ingest_guidance_docs,
}

async def run_ingestion(
    sources: list[str] | None = None,
    session: AsyncSession,
    s3_client: S3Client,
    config: IngestionConfig,
) -> list[IngestionResult]:
    targets = sources or list(REGISTERED_SOURCES.keys())
    results = []
    for name in targets:
        handler = REGISTERED_SOURCES[name]
        result = await handler(session, s3_client, config)
        results.append(result)
    return results
```

**Adding a new source = two steps:**
1. Create a new file in `sources/` with the standard function signature.
2. Add one line to `REGISTERED_SOURCES` in `runner.py`.

No other files change.

---

## IngestionResult Model

Every parser returns this:

```python
# ingestion/pipeline/models.py
from pydantic import BaseModel
from datetime import datetime

class IngestionResult(BaseModel):
    source: str
    ingestion_type: str              # "full" | "incremental"
    started_at: datetime
    completed_at: datetime
    records_processed: int
    records_added: int
    records_updated: int
    records_removed: int
    records_skipped: int             # validation failures
    status: str                      # "completed" | "completed_with_errors" | "failed" | "skipped_unchanged"
    error_message: str | None = None
    source_vintage: datetime | None = None
```
