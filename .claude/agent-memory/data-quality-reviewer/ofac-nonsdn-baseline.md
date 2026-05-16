---
name: ofac-nonsdn-baseline
description: OFAC Non-SDN data quality baseline from 2026-05-16 review. Record counts, field coverage percentages, and known parser gaps.
metadata:
  type: project
---

## OFAC Non-SDN Data Quality Baseline (2026-05-16)

**Record count**: 442 (363 entities, 79 individuals)
**Source file**: `ingestion/data/ofac_nonsdn/cons_prim.csv` (443 lines, 1 trailing EOF marker)
**Last ingestion**: 2026-05-15 19:01 UTC, status `completed_with_errors` (1 skip = EOF line)

### Field Coverage Benchmarks

| Field | Coverage | Notes |
|-------|----------|-------|
| programs | 100% | All valid codes |
| DOB (individuals) | 93.7% (74/79) | 5 genuinely lack DOB in source |
| nationality (individuals) | 2.5% (2/79) | Source limitation, NOT parser bug |
| country_of_registration (entities) | 0% (12 extractable) | Parser gap |
| remarks | 100% | Includes extended remarks from cons_comments.csv |
| raw_record | 100% | |
| Aliases linked | 89% of entities (395/442) | |
| Addresses linked | 88% of entities (390/442) | |
| Identifiers linked | 62% of entities (272/442) | |

### Known Parser Gaps (shared with SDN)
- Inline `a.k.a.` aliases from remarks NOT extracted (69 aliases across 56 entities)
- "Nationality of Registration" NOT extracted to country_of_registration (12 records)
- "Driver's License No." NOT in IDENTIFIER_PATTERNS (1 record)
- These are tracked in `.tmp/dqr-ofac-nonsdn.md` issues W1, W2, W3

### Source Characteristics
- 363 entities have NULL sdn_type (raw: `-0-`), correctly defaulted to `entity`
- Program codes: 11 unique values, all valid OFAC format
- Multi-program records: 90 with 2 programs, 1 with 3 programs
- All names are ASCII (no encoding concerns for this source)
- EOF marker (Ctrl-Z) at end of cons_prim.csv is expected OFAC file artifact

**Why:** Future reviews can compare against these baselines to detect regressions (e.g., nationality coverage dropping, alias count changing unexpectedly).

**How to apply:** When reviewing ofac_nonsdn in future sessions, compare current metrics against these baselines. Flag any drops of >5% in coverage metrics as potential regressions.
