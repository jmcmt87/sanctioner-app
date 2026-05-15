# Source Parsers

Each file in this directory handles ingestion for one sanctions data source. All parsers follow the same pattern: read source files, normalize records into a standard dict format, call `upsert_entities()` to load into PostgreSQL, and log the run to `ingestion_log`.

## Source Inventory

| Source | File | Format | Refresh | Status |
| ------ | ---- | ------ | ------- | ------ |
| OFAC SDN List | `ofac_sdn.py` | CSV (pipe-delimited, 4 files) | Daily | Implemented |
| OFAC Non-SDN List | `ofac_nonsdn.py` | CSV (pipe-delimited, 4 files) | Daily | Implemented |
| EU Consolidated List | `eu_sanctions.py` | XML (lxml, namespace-aware) | Daily | Implemented |
| OFAC Vessels | `ofac_vessels.py` | -- | Daily | Not started |
| Enforcement Actions | `enforcement.py` | PDF | Monthly | Not started |
| EU Regulations | `regulations.py` | HTML/PDF | Weekly check | Not started |
| Guidance/FAQs | `guidance.py` | HTML/PDF | Monthly | Not started |

## Adding a New Source

1. Create a new file in this directory: `new_source.py`
2. Implement the standard function signature:
   ```python
   async def ingest_new_source(session: AsyncSession, data_dir: Path) -> IngestionResult:
   ```
3. Parse source files into dicts matching the `upsert_entities()` format:
   ```python
   {"source", "source_id", "entity_type", "primary_name", "programs", "legal_basis",
    "date_of_birth", "nationality", "country_of_registration", "remarks", "list_date",
    "last_updated", "data_vintage", "raw_record",
    "aliases": [{"alias_name", "alias_type", "is_primary"}],
    "addresses": [{"address", "city", "country", "postal_code"}],
    "identifiers": [{"id_type", "id_value", "country"}],
    "vessels": [{"vessel_name", "imo_number", ...}]}
   ```
4. Register in `runner.py`:
   ```python
   REGISTERED_SOURCES["new_source"] = ingest_new_source
   SOURCE_FILES["new_source"] = ["new_source/*.csv"]
   ```
5. Update this README's source inventory table.

## Parser Details

**ofac_sdn.py** -- Parses 4 OFAC CSV files (sdn.csv, add.csv, alt.csv, sdn_comments.csv). Extracts dates of birth, nationalities, identifiers, and vessel data (IMO, MMSI, build year) from semi-structured remarks via regex. Also exports shared helpers used by `ofac_nonsdn.py`.

**ofac_nonsdn.py** -- Reuses parsing helpers from `ofac_sdn.py` with different file paths and source name. Covers the Consolidated Non-SDN lists (cons_prim.csv, cons_add.csv, cons_alt.csv, cons_comments.csv).

**eu_sanctions.py** -- Parses the EU Consolidated Financial Sanctions List XML using lxml with namespace-aware XPath. Selects English strong names as primary, extracts citizenships, birthdates, addresses, identifications, and regulation references from `numberTitle` attributes.
