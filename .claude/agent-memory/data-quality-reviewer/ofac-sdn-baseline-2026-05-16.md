---
name: ofac-sdn-baseline-2026-05-16
description: OFAC SDN data quality baseline — 18,959 records, key field coverage percentages, known gaps (no relationships, missing identifier types), and parser behaviors observed on 2026-05-16
metadata:
  type: project
---

## OFAC SDN Data Quality Baseline (2026-05-16)

**Records**: 18,959 (9,670 entities, 7,465 individuals, 1,480 vessels, 344 aircraft)
**Last vintage**: 2026-05-15 18:55 UTC

### Field Coverage Benchmarks
- programs: 100%
- date_of_birth (individuals): 96.8% (7,229/7,465)
- nationality (individuals): 73.0% (5,451/7,465)
- remarks: 98.2%
- raw_record: 100%
- country_of_registration: 0% (not in source)
- list_date: 0% (not in source)

### Related Table Counts
- entity_aliases: 20,296 (50% of entities have aliases)
- entity_addresses: 21,522 (99.2% entity coverage, 82.4% individual coverage)
- entity_identifiers: 12,722 (11 types extracted)
- vessels: 1,480 (100% match with entity_type='vessel')
- entity_relationships: 0 (NOT IMPLEMENTED)

### Known Gaps
1. Relationship extraction not implemented (8,043 records have "Linked To:" in remarks)
2. ~1,356 entities have unextracted identifier types (C.U.R.P., R.F.C., USCC, SWIFT/BIC, etc.)
3. 1 record skipped per run (trailing CSV line) — benign

### Parser Behaviors
- OFAC SDN CSV read with `encoding="utf-8", errors="replace"` (line 125)
- Program codes parsed from `"] ["` delimited format
- Entity type: NULL sdn_type maps to 'entity', others map directly
- All names are ASCII-only (OFAC uses transliteration)
- 2 non-standard MMSI values faithfully extracted from source (10-digit and 7-digit)

**Why:** Establishes a baseline for regression detection in future reviews. If nationality drops below 73% or aliases below 50%, something changed.

**How to apply:** Compare future OFAC SDN review metrics against these numbers. Flag any drops >5% as potential parser regression.
