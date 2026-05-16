---
name: eu-consolidated-baseline-2026-05-16
description: EU Consolidated source baseline - 5,996 records, critical legal_basis regex bug (46.8% missing), field coverage benchmarks
metadata:
  type: project
---

## EU Consolidated Source Baseline (2026-05-16)

**Records**: 5,996 (4,410 individuals, 1,586 entities)
**Data vintage**: 2026-05-08
**Source**: `source = 'eu_consolidated'`

### Field Coverage Benchmarks

| Field | Coverage | Notes |
|-------|----------|-------|
| legal_basis | 53.2% (3,188) | CRITICAL BUG - regex drops 46.8% |
| programs (EU regime codes) | 100% | Design decision - stores EU programme codes |
| nationality (individuals) | 59.3% (2,617/4,410) | Source limitation, not parser bug |
| date_of_birth (individuals) | 84.3% (3,718/4,410) | Good |
| country_of_registration (entities) | 0% | Not extracted, source doesn't provide directly |
| raw_record | 100% | All records have audit trail |
| list_date | 90.3% | Good |
| remarks | 11.6% | Source-driven sparsity |

### Child Table Coverage

| Table | Entities with records | Coverage |
|-------|----------------------|----------|
| entity_aliases | 5,271 | 87.9% |
| entity_addresses | 1,862 | 31.1% |
| entity_identifiers | 1,769 | 29.5% |
| entity_relationships | 0 | 0% (expected, EU XML lacks structured relationships) |

### Critical Bug: legal_basis Regex

**File**: `ingestion/pipeline/sources/eu_sanctions.py` line 29
**Regex**: `r"(\d+/\d{4})"` -- requires exactly 4 digits after slash
**Fix**: Change to `r"(\d+/\d+)"` to match regulation numbers like `2020/716`, `2022/332`, `2025/44`
**Impact**: 2,808 records will gain legal_basis values after fix

### Known Edge Cases

- 2 Iranian records with Solar Hijri calendar years (EU.6135.22, EU.6140.93) stored as pre-1900 dates
- 15 records with non-standard regulation formats (UNLI prefix, double-slash)
- 580 DOB records default to Jan 1 when source only provides year
- Alias types use `aka (LANG_CODE)` format, not standard `{aka, fka, nka}`

**Why:** Baseline for tracking regressions. After regex fix, legal_basis should reach ~99.7%.
**How to apply:** Compare future reviews against these numbers to detect improvements or regressions.
