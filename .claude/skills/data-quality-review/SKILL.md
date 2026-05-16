---
name: data-quality-review
description: >
  Companion skill for the data-quality-reviewer agent. Contains field-by-field validation
  checklists, encoding rules, critical article coverage checklists, PDF artifact detection
  heuristics, program code validation, and sample comparison methodology for every data
  source and table in the project. The agent provides the persona and boundaries; this
  skill provides the checklists and rules. Also used by the Builder when writing parser
  tests — the validation rules here define what "correctly parsed" means.
---

# Data Quality Review Skill

This skill defines what "correct data" looks like for every table and source in the
Sanctions Screening Assistant. The data-quality-reviewer agent uses these checklists
to audit ingested data. The Builder can also reference these rules when writing parser
unit tests.

---

## Validation Checklists by Table

### sanctioned_entities

#### Universal Rules (all sources)

| Field | Rule | Check |
|-------|------|-------|
| `id` | UUID, auto-generated | Never NULL. Never duplicated. |
| `source` | One of: `ofac_sdn`, `eu_consolidated`, `ofac_nonsdn`, `eu_269` | No other values. No NULLs. |
| `source_id` | Non-empty string, unique within source | `SELECT source, source_id, COUNT(*) ... HAVING COUNT(*) > 1` to find duplicates. |
| `entity_type` | One of: `individual`, `entity`, `vessel`, `aircraft` | No other values. No NULLs. |
| `primary_name` | Non-empty string | No NULLs. No empty strings. No strings that are just whitespace. |
| `data_vintage` | Timezone-aware timestamp | Never NULL. Must be within the last 7 days for daily sources. |
| `last_updated` | Timezone-aware timestamp | Never NULL. Must be ≥ data_vintage. |
| `raw_record` | JSONB, non-null | Every record MUST have raw_record populated — it's the audit trail. |

#### OFAC-Specific Rules (source = 'ofac_sdn' or 'ofac_nonsdn')

| Field | Rule | Check |
|-------|------|-------|
| `programs` | Non-empty text array | OFAC entities always have at least one program. `WHERE source LIKE 'ofac%' AND (programs IS NULL OR array_length(programs, 1) IS NULL)` should return 0 rows. |
| `legal_basis` | Should be NULL or empty | OFAC uses programs, not legal_basis. If legal_basis is populated for OFAC records, the parser is cross-contaminating fields. |
| `date_of_birth` | Date format, for individuals only | Check: `WHERE source LIKE 'ofac%' AND entity_type = 'individual' AND date_of_birth IS NOT NULL` — DOB should be present for a significant portion of individuals (not all — OFAC doesn't always provide it). Flag if <30% population. |
| `nationality` | May be present but often sparse for OFAC | OFAC provides nationality less consistently than the EU. Low population is expected but not zero. |
| `country_of_registration` | For entities only | Should be NULL for individuals. May be sparsely populated for entities. |
| `remarks` | Text, may be lengthy | Often contains critical operational info (links to other entities, vessel info, program details). Should be populated for most records. |

**OFAC source_id format**: OFAC uses numeric entry IDs. Verify they're numeric strings.

**OFAC entity_type mapping**: OFAC raw data has finer distinctions (e.g., "Individual", "Entity", "Vessel", "Aircraft", and sub-types like "Government Entity", "Organization"). The parser normalizes to four types. Verify:
- "Individual" → `individual`
- "Vessel" → `vessel`
- "Aircraft" → `aircraft`
- Everything else (Entity, Government Entity, Organization, etc.) → `entity`

The original OFAC sub-type must be preserved in `raw_record` JSONB.

**OFAC program code validation**: OFAC uses specific standardized program tags. Run:
```sql
SELECT DISTINCT unnest(programs) as program
FROM sanctioned_entities WHERE source LIKE 'ofac%'
ORDER BY program;
```

Known valid program code patterns (not exhaustive, but representative):
- Country/EO format: `RUSSIA-EO14024`, `UKRAINE-EO13662`, `IRAN`, `SYRIA`, `CUBA`, `DPRK`
- Thematic programs: `SDGT` (terrorism), `SDNTK` (narcotics), `CYBER2`, `GLOMAG` (Magnitsky)
- Hyphenated EO references: `*-EO*` pattern

Flag as Critical:
- Multiple program codes concatenated into a single string without array separation
- Empty strings in the programs array
- Values with extra whitespace, line breaks, or control characters
- Values that don't resemble any known OFAC program code format

#### EU-Specific Rules (source = 'eu_consolidated' or 'eu_269')

| Field | Rule | Check |
|-------|------|-------|
| `legal_basis` | Non-empty text array | EU entities should have legal_basis populated (e.g., `['Reg. 269/2014']`, `['Reg. 833/2014']`). `WHERE source LIKE 'eu%' AND (legal_basis IS NULL OR array_length(legal_basis, 1) IS NULL)` should return very few rows. |
| `programs` | Should be NULL or empty | EU uses legal_basis, not programs. If programs is populated for EU records, the parser is cross-contaminating. |
| `nationality` | For individuals — CRITICAL | EU regulations (especially Art. 5b of 833/2014) apply based on nationality. The EU XML provides nationality as a structured field. If nationality is missing for EU individuals, **this is a parsing failure, not a data limitation**. Flag as Critical. Check: `WHERE source LIKE 'eu%' AND entity_type = 'individual' AND (nationality IS NULL OR array_length(nationality, 1) IS NULL)` — should be very low (some entries genuinely lack nationality in the XML). |
| `date_of_birth` | For individuals | The EU XML provides DOB as a structured field. Higher population expected than OFAC. Flag if <50% for EU individuals. |
| `country_of_registration` | For entities | EU XML usually provides this. Flag if <40% for EU entities. |

**EU source_id format**: EU uses alphanumeric reference codes. Verify they match the format from the XML (typically like `EU.1234.56`).

---

### entity_aliases

| Field | Rule | Check |
|-------|------|-------|
| `entity_id` | Valid FK to sanctioned_entities | No orphaned aliases. `LEFT JOIN` check. |
| `alias_name` | Non-empty string | No NULLs. No empty strings. No duplicates within the same entity. |
| `alias_type` | One of: `aka`, `fka`, `nka`, or NULL | No other values. |
| `is_primary` | Boolean | Exactly one primary alias per entity (or zero if primary_name on the entity is sufficient). `SELECT entity_id, COUNT(*) FROM entity_aliases WHERE is_primary = true GROUP BY entity_id HAVING COUNT(*) > 1` should return 0 rows. |

**Coverage check**: Most sanctioned entities have at least one alias. Count entities with zero aliases per source and flag if unusually high (>50%).

---

### vessels

| Field | Rule | Check |
|-------|------|-------|
| `entity_id` | Valid FK to sanctioned_entities | No orphaned vessels. The parent entity should have `entity_type = 'vessel'`. |
| `imo_number` | 7-digit numeric string (IMO standard) | Format check: `WHERE imo_number !~ '^\d{7}$' AND imo_number IS NOT NULL`. IMO numbers are always exactly 7 digits. |
| `mmsi_number` | 9-digit numeric string (ITU standard) | Format check: `WHERE mmsi_number !~ '^\d{9}$' AND mmsi_number IS NOT NULL`. |
| `vessel_name` | Non-empty string | Should be populated for all vessel records. May differ from parent entity's primary_name (vessels get renamed). |
| `flag` | Country name or code | Should be populated for most vessels. |
| `vessel_type` | Descriptive string | E.g., "Crude Oil Tanker", "Bulk Carrier". Should be populated for most OFAC vessel records. |
| `call_sign` | Alphanumeric string | May be sparsely populated. |
| `build_year` | 4-digit integer, reasonable range | `WHERE build_year IS NOT NULL AND (build_year < 1950 OR build_year > 2026)` should return 0 rows. |
| `tonnage` | Numeric string | May be sparsely populated. |

**Cross-check**: Every vessel in the `vessels` table should have a corresponding sanctioned_entity with `entity_type = 'vessel'`. And every sanctioned_entity with `entity_type = 'vessel'` should have a vessels record. Flag mismatches.

---

### entity_addresses

| Field | Rule | Check |
|-------|------|-------|
| `entity_id` | Valid FK | No orphans. |
| `country` | Non-empty for most addresses | Flag if >30% missing country. |
| `address` | Text | May be partial. |

---

### entity_identifiers

| Field | Rule | Check |
|-------|------|-------|
| `entity_id` | Valid FK | No orphans. |
| `id_type` | Descriptive string | E.g., "Passport", "Tax ID Number", "Registration Number". |
| `id_value` | Non-empty string | No NULLs. |

---

### entity_relationships

| Field | Rule | Check |
|-------|------|-------|
| `from_entity_id` | Valid FK | Both FKs must resolve. |
| `to_entity_id` | Valid FK | Both FKs must resolve. |
| `relationship_type` | One of: `owner`, `subsidiary`, `operates`, `linked_to` | No other values. |
| `ownership_percentage` | Numeric 0–100, or NULL | `WHERE ownership_percentage IS NOT NULL AND (ownership_percentage < 0 OR ownership_percentage > 100)` should return 0 rows. |
| `source` | Non-empty | Where this relationship was extracted from. |

**Self-reference check**: `WHERE from_entity_id = to_entity_id` should return 0 rows.

**Unique constraint check**: No duplicate (from, to, type) combinations.

**Coverage note**: Relationship data will be partial. The CLAUDE.md schema acknowledges this — the RAG layer supplements SQL relationships with contextual references from enforcement docs. Do not set unrealistic expectations for relationship table completeness. But whatever IS in the table must be valid.

---

### document_chunks

| Field | Rule | Check |
|-------|------|-------|
| `content` | Non-empty text | No NULLs. No empty strings. No chunks that are just whitespace or boilerplate headers. |
| `embedding` | Vector of correct dimension (1024 for bge-m3) | No NULLs for chunks that should be searchable. Dimension check: query a sample and verify vector length. |
| `source_document` | Non-empty string (S3 key or identifier) | No NULLs. |
| `source_title` | Human-readable document title | Should be populated for all chunks. |
| `jurisdiction` | One of: `US`, `EU`, `DE` | No other values. No NULLs. |
| `document_type` | One of: `enforcement`, `regulation`, `guidance`, `faq`, `general_license` | No other values. No NULLs. |
| `article_reference` | For regulation/guidance chunks | `WHERE document_type = 'regulation' AND article_reference IS NULL` — flag if >20% of regulation chunks lack article references. |
| `chunk_index` | Non-negative integer | Sequential within each source_document. `SELECT source_document, MIN(chunk_index), MAX(chunk_index), COUNT(*) FROM document_chunks GROUP BY source_document` to check for gaps. |
| `published_date` | Date | Should be populated for all chunks. |
| `ingestion_timestamp` | Timezone-aware timestamp | Never NULL. |
| `data_vintage` | Timezone-aware timestamp | Never NULL. |

**Chunk quality checks:**
- Minimum chunk length: flag chunks under 50 characters (likely parsing artifacts or headers).
- Maximum chunk length: flag chunks over 3,500 characters (likely failed splitting — at ~500 token target, anything over ~3,500 chars is probably a chunking failure that will dilute semantic signal during retrieval).
- Jurisdiction consistency: all chunks from the same source_document should have the same jurisdiction. `SELECT source_document, COUNT(DISTINCT jurisdiction) FROM document_chunks GROUP BY source_document HAVING COUNT(DISTINCT jurisdiction) > 1`.

---

### ingestion_log

| Field | Rule | Check |
|-------|------|-------|
| `source` | Non-empty | Every ingestion run must be logged. |
| `status` | One of: `completed`, `completed_with_errors`, `failed`, `skipped_unchanged` | No other values. |
| `records_processed` | Non-negative integer | Should be > 0 for completed runs. |
| `source_vintage` | Timezone-aware timestamp | Should be populated for completed runs. |

**Freshness check per source:**
| Source | Expected Refresh | Alert If Older Than |
|--------|-----------------|---------------------|
| ofac_sdn | Daily | 3 days |
| eu_consolidated | Daily | 3 days |
| ofac_nonsdn | Daily | 3 days |
| ofac_enforcement | Monthly | 45 days |
| regulations | After amendment | 14 days (check EUR-Lex weekly) |
| guidance | Quarterly | 120 days |

**Missing run detection** (Critical — catches silent pipeline failures):
A daily source that simply doesn't run produces no log entry and no error. Check that
every expected daily source has at least one successful (`completed` or `skipped_unchanged`)
ingestion log entry within the last 3 days. If not, flag as Critical — the pipeline may
have silently stopped running while the data goes stale.

---

## Encoding & Character Integrity Rules

Sanctions data is inherently multilingual. Transliterated Russian, Arabic, and Chinese
names are the norm for OFAC and EU lists. Encoding corruption is a silent killer —
records look populated, field counts are fine, but name searches return nothing because
characters were garbled during parsing.

### Mandatory Encoding Checks

**For every source, every review:**

1. **Sample non-Latin records**: Pull 20–30 records with non-ASCII characters in
   `primary_name` and `entity_aliases.alias_name`. Visually inspect for corruption.

2. **Check for replacement characters**: `WHERE primary_name LIKE '%�%'` (U+FFFD).
   Any hits = Critical. This means the parser encountered bytes it couldn't decode.

3. **Check for mojibake patterns**: Look for sequences like `Ð` followed by other
   characters, `Ã©` instead of `é`, or `Â` appearing before accented characters.
   These indicate double-encoded UTF-8. Flag as Critical.

4. **Compare against raw_record**: For flagged records, check if `raw_record` JSONB
   has the correct characters. If raw_record is correct but `primary_name` is garbled,
   the mapping step damaged the data. If raw_record is also garbled, the parsing step
   damaged the data.

5. **Check alias completeness for multilingual entities**: Some entities have names in
   multiple scripts (Latin + Cyrillic, Latin + Arabic). Verify that the EU list's
   multi-script names are all captured as separate aliases, not merged or dropped.

### Source-Specific Encoding Notes

- **EU Consolidated List XML**: Provides names in multiple scripts. The XML is UTF-8
  encoded. If the parser doesn't explicitly handle UTF-8, non-Latin names will be
  damaged. EU names also include diacritics on European names (ü, ö, ä, ñ, etc.) —
  verify these survive parsing.

- **OFAC SDN CSV**: Uses transliterated Latin characters for most names, but the
  remarks field and some alias entries contain characters outside basic ASCII.
  The CSV encoding should be verified (OFAC uses UTF-8 or Latin-1 depending on the
  download source).

- **Enforcement PDFs**: Non-Latin characters in entity names within PDF text depend
  entirely on PDF extraction quality. Flag any extracted text where entity names
  known to contain non-Latin characters appear garbled.

### Severity

- Replacement characters (U+FFFD) in any name field → **Critical**
- Mojibake patterns in name fields → **Critical**
- Dropped diacritics (Müller → Mller) → **Warning** (search may still work but is degraded)
- Non-Latin aliases missing from EU entities that have them in the XML → **Critical**
- Encoding issues only in `remarks` or low-priority text fields → **Warning**

---

## PDF Extraction Artifact Detection

Enforcement action PDFs and guidance documents may produce garbled text due to
non-standard fonts, scanned pages, or complex formatting. This is a known issue
with the Commerzbank settlement document in particular.

### Detection Heuristics

1. **Printable character ratio**: For each chunk, calculate the ratio of standard
   printable characters (a-z, A-Z, 0-9, common punctuation, whitespace) to total
   characters. If below 70%, flag for inspection.

2. **High special character density**: Chunks with an unusually high ratio of
   special characters (°, §, ±, ©, ®, etc.) relative to alphabetic characters
   may indicate font mapping failures where the PDF used custom character encodings.

3. **Repeated nonsense sequences**: Patterns like `....`, `????`, `####`, or
   repeated Unicode blocks that don't form words suggest extraction failure.

4. **Very short chunks from long PDFs**: If a 25-page PDF produces only a handful
   of short chunks, the extractor likely failed on most pages (possibly scanned/image
   pages mixed with text pages).

5. **Missing expected content**: For known documents (Commerzbank settlement, BNP
   Paribas settlement), spot-check that key factual findings appear in the chunks.
   If the chunks are all garbled headers and footers, the extraction failed.

### Severity

- Chunks where <70% of characters are printable → **Warning** (inspect manually)
- Chunks where <50% of characters are printable → **Critical** (extraction failure)
- Known critical document (Commerzbank settlement) with garbled extraction → **Critical**
- Minor artifacts (stray bullet characters, occasional special chars) → **Info**

---

## Critical Regulation Article Coverage

Generic completeness checks (is `article_reference` populated?) are necessary but not
sufficient. The agent must also verify that the specific articles analysts query most
frequently are actually represented in the chunks.

### Reg. 833/2014 — Critical Articles Checklist

Every one of these must have at least one chunk with a matching `article_reference`:

| Article | Topic | Why It's Critical |
|---------|-------|-------------------|
| Art. 3a | Import restrictions on Russian goods | Major trade restriction |
| Art. 3n | Oil price cap mechanism | Maritime sanctions — high-volume analyst queries |
| Art. 5 | Financial restrictions — securities | Core financial sanctions |
| Art. 5a | Financial restrictions — money market | Core financial sanctions |
| Art. 5aa | Public financing/financial assistance | Frequently queried |
| Art. 5b | Deposit restrictions for Russian nationals | One of the most common analyst questions |
| Art. 5e | Trust services | Frequently queried |
| Art. 5f | Credit rating services | Sector-specific restriction |
| Art. 5g | Crypto asset wallets | Increasingly relevant |
| Art. 5h | Central securities depositories | Financial infrastructure |
| Art. 5k | Insurance/reinsurance | Maritime and trade sanctions |
| Art. 12 | Anti-circumvention | Cited in virtually every investigation |

**Check query:**
```sql
SELECT article_reference, COUNT(*) FROM document_chunks
WHERE source_document LIKE '%833%'
  AND document_type = 'regulation'
  AND article_reference IS NOT NULL
GROUP BY article_reference
ORDER BY article_reference;
```

**Severity:**
- Any article from this list with zero chunks → **Critical**
- Article present but with only 1 chunk when the article is lengthy (e.g., Art. 5b has
  multiple paragraphs and sub-paragraphs) → **Warning** (possible incomplete extraction)

### Reg. 269/2014 — Minimum Coverage

- Verify chunks exist with `jurisdiction = 'EU'` and `document_type = 'regulation'`
- Verify source_document references Reg. 269/2014

### OFAC 50% Rule Guidance — Minimum Coverage

- Verify at least one chunk exists with `document_type = 'guidance'` that references
  the 50% Rule (check content text or source_document for "50 percent" or "50%").
- This is one of the most frequently referenced documents in entity screening.

### OFAC General Licenses — Coverage Check

```sql
SELECT source_document, COUNT(*) FROM document_chunks
WHERE document_type = 'general_license'
GROUP BY source_document;
```

Verify that key Russia-related General Licenses are represented (GL 13, GL 15, GL 44
at minimum). Missing General Licenses means the tool can identify what's blocked but
cannot tell analysts what's authorized.

---

## Sample Comparison Methodology

For each ingested source, compare a sample of parsed database records against the raw
source file.

### How to Sample
1. Pull 10–20 records from the database for the source being reviewed.
2. Select a mix: 5 records with the most populated fields, 5 with the sparsest fields,
   and 5–10 random.
3. Include at least 3–5 records with non-Latin characters in their names (if the source
   has any) to verify encoding integrity.
4. Locate the same records in the raw source file (match by source_id).

### What to Compare

**For OFAC SDN (CSV):**
- Primary name matches the `SDN_NAME` field in the CSV
- All aliases from `alt.csv` are present in entity_aliases
- Programs match the `PROGRAM` field — verify each program is a separate array element
- Entity type mapping is correct
- Addresses from `add.csv` are linked
- Identifiers from the CSV are in entity_identifiers
- Remarks text is preserved completely (no truncation)
- Vessel records have IMO numbers extracted from remarks or the vessel fields
- Non-Latin characters in names and remarks survived parsing

**For EU Consolidated List (XML):**
- Primary name matches the XML `<wholeName>` or `<firstName>`+`<lastName>` composite
- Nationality extracted from `<citizenship>` elements
- Date of birth extracted from `<birthdate>` elements
- Legal basis extracted from `<regulation>` elements
- Addresses from `<address>` elements are linked
- All aliases from `<nameAlias>` elements are present
- Multi-script names (Latin + Cyrillic, Latin + Arabic) are all captured
- Diacritics preserved (ü, ö, ä, etc.)

**For Document Chunks (PDFs/HTML):**
- Open the raw PDF/HTML and verify that the chunk content is a faithful extraction
- Check that chunk boundaries don't split mid-sentence in problematic ways
- Verify article_reference is correct for regulation chunks (spot-check 5 chunks)
- Confirm jurisdiction tagging matches the source document's origin
- Check for PDF extraction artifacts (garbled text, font encoding issues)
- For enforcement actions: verify that key factual findings and penalty amounts
  appear in the chunks, not just headers and footers

### Reporting Comparison Results

For each sampled record, report:
```
Record [source_id]: [primary_name]
- Fields matched: [list]
- Discrepancies: [list with details]
- Data lost in parsing: [anything in raw not captured]
- Encoding: [PASS if non-Latin chars correct, FAIL if garbled, N/A if only ASCII]
- Assessment: PASS / PARTIAL / FAIL
```

---

## Cross-Source Consistency Checks

Some entities appear on both OFAC and EU lists. While full deduplication is out of scope
for the data quality reviewer (that's a product decision), you should flag obvious indicators:

```sql
-- Entities with very similar names across sources (potential cross-list matches)
-- This is informational, not a bug — just useful context
SELECT a.source, a.primary_name, b.source, b.primary_name
FROM sanctioned_entities a
JOIN sanctioned_entities b ON similarity(a.primary_name, b.primary_name) > 0.8
WHERE a.source != b.source AND a.id < b.id
LIMIT 20;
```

Report this as informational context, not as an issue. Dual-listing is expected and intentional.

---

## Escalation Boundaries

**Flag for human review when:**
- A field is missing and you can't determine from the raw source data whether it's a parser bug or the source genuinely doesn't provide it.
- An entity_type mapping seems wrong but the raw data is ambiguous (e.g., is a state-owned bank an "entity" or should it have a special sub-type?).
- Relationship data is present in remarks/notes but not extracted into entity_relationships — this may require domain knowledge to interpret.
- Date formats in the source are ambiguous (DD/MM/YYYY vs. MM/DD/YYYY).
- A large number of records are missing a field that previous ingestion runs had populated (possible regression).
- Non-Latin character handling looks wrong but you can't tell if the source or the parser is at fault.
- OFAC program codes you haven't seen before — could be new legitimate codes or parsing artifacts.

**Never attempt to answer:**
- "Should this entity be sanctioned?"
- "Is this the correct sanctions program/regulation for this entity?"
- "Does this transaction violate sanctions?"
- "Is this General License applicable?"
- Any question that requires interpreting sanctions law rather than checking data structure.