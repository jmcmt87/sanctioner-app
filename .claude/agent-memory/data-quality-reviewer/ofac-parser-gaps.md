---
name: ofac-parser-gaps
description: Known parser limitations in ingestion/pipeline/sources/ofac_sdn.py that affect both SDN and Non-SDN ingestion. Identified 2026-05-16.
metadata:
  type: project
---

## OFAC Parser Known Gaps (as of 2026-05-16)

File: `ingestion/pipeline/sources/ofac_sdn.py` (shared by both ofac_sdn and ofac_nonsdn)

### 1. Inline a.k.a. aliases not extracted from remarks
- Pattern: `a.k.a. 'NAME'` in remarks text
- Impact: ~2,568 SDN entities + 56 Non-SDN entities have aliases only in remarks
- These come from extended remarks (cons_comments.csv) where OFAC puts overflow alias data
- The parser only reads aliases from alt.csv/cons_alt.csv

### 2. country_of_registration not extracted
- Pattern: `Nationality of Registration COUNTRY` in remarks
- Impact: 15 SDN + 12 Non-SDN entities
- Field exists in schema but is never populated for OFAC sources

### 3. Driver's License not in IDENTIFIER_PATTERNS
- Pattern: `Driver's License No. VALUE (COUNTRY)` in remarks
- Impact: 27 SDN + 1 Non-SDN records
- Easy fix: add to IDENTIFIER_PATTERNS list

### 4. EOF marker causes `completed_with_errors`
- OFAC CSV files have trailing Ctrl-Z (0x1A) character
- Parser counts this as a skipped record, triggering non-`completed` status
- No data loss, purely cosmetic

**Why:** These gaps are consistent across both OFAC sources. Any fix should be applied once in the shared code and will benefit both sources simultaneously.

**How to apply:** When the builder fixes these, verify by re-running the Non-SDN ingestion (smaller dataset, faster iteration) before running against the full SDN list.
