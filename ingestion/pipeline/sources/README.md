# Source Parsers

Each file in this directory handles ingestion for one sanctions data source. Structured parsers (OFAC SDN, Non-SDN, EU) normalize records into a standard dict format and call `upsert_entities()` to load into `sanctioned_entities`. Unstructured parsers (enforcement, guidance) extract PDF text, chunk it, generate embeddings, and store in `document_chunks` for RAG retrieval. All parsers log every run to `ingestion_log`.

---

## Source Inventory

| Source | File | Format | Refresh | Status |
| ------ | ---- | ------ | ------- | ------ |
| OFAC SDN List | `ofac_sdn.py` | CSV (4 files) | Daily | Implemented |
| OFAC Non-SDN Consolidated List | `ofac_nonsdn.py` | CSV (4 files) | Daily | Implemented |
| EU Consolidated Financial Sanctions List | `eu_sanctions.py` | XML (lxml) | Daily | Implemented |
| Enforcement Actions | `enforcement.py` | PDF (20 docs) | Monthly | Implemented |
| OFAC Guidance | `guidance.py` | PDF (2 docs) | Quarterly | Implemented |
| OFAC General Licenses | — | PDF | Weekly | Not started |
| EU Regulations (833/2014, 269/2014) | — | HTML/PDF | Weekly check | Not started |

---

## OFAC SDN List (Specially Designated Nationals and Blocked Persons)

### What It Is

The SDN List is the primary US sanctions enforcement tool. It identifies individuals, entities, vessels, and aircraft whose property and interests in property are **blocked** (frozen) by OFAC. US persons are generally prohibited from dealing with SDN-listed parties, and non-US persons face **secondary sanctions risk** for certain categories of transactions.

**Issuing authority**: Office of Foreign Assets Control (OFAC), US Department of the Treasury

**Legal framework**: International Emergency Economic Powers Act (IEEPA), plus multiple Executive Orders depending on the program (EO 14024 for Russia, EO 13846 for Iran, etc.)

**Consequence of designation**: Full blocking. All property and interests in property subject to US jurisdiction are frozen. Any US person (or person using the US financial system) that processes a transaction involving an SDN-listed party faces strict liability.

### Entity Composition

| Entity Type | Count | % of Total |
|-------------|-------|-----------|
| entity | 9,670 | 51.0% |
| individual | 7,465 | 39.4% |
| vessel | 1,480 | 7.8% |
| aircraft | 344 | 1.8% |
| **Total** | **18,959** | 100% |

### Sanctions Programs (Top 10)

| Program Code | Records | Authority |
|-------------|---------|-----------|
| RUSSIA-EO14024 | 6,392 | Russia Harmful Foreign Activities Sanctions |
| SDGT | 3,116 | Specially Designated Global Terrorist |
| IFSR | 1,504 | Iran Financial Sanctions Regulations |
| SDNTK | 1,412 | Narcotics Trafficker Kingpin |
| NPWMD | 1,159 | WMD Proliferators Sanctions |
| GLOMAG | 742 | Global Magnitsky Human Rights |
| IRAN-EO13902 | 726 | Iran petroleum/petrochemical sector |
| IRAN | 669 | Iran Transactions & Sanctions Regulations |
| ILLICIT-DRUGS-EO14059 | 618 | Illicit Drugs (fentanyl supply chains) |
| UKRAINE-EO13662 | 533 | Ukraine-Related (sectoral) |

Total unique programs: **76**, spanning Russia/Ukraine, Iran, DPRK, terrorism, narcotics, cyber, human rights, and regional conflicts. Russia/Ukraine entries alone account for 35.7% of all SDN records.

### Field Coverage

| Field | Coverage | Compliance Significance |
|-------|----------|------------------------|
| `primary_name` | 100% | Primary screening match field |
| `programs` | 100% | Determines which authority applies and what is prohibited |
| `remarks` | 98.2% | Semi-structured text: identifiers, DOBs, relationships, secondary sanctions flags |
| `date_of_birth` | 96.8% of individuals | First disambiguation check for name matches |
| `nationality` | 73.0% of individuals | Determines jurisdiction applicability (EU Art. 5b targets Russian nationals) |
| `country_of_registration` | 0.2% of entities | Very sparse in source data |

### Related Records

| Table | Records | Notes |
|-------|---------|-------|
| entity_aliases | 24,665 | From alt.csv + inline a.k.a./f.k.a. in remarks |
| entity_addresses | 21,522 | 83% of entities have at least one address |
| entity_identifiers | 15,068 | 41 identifier types (Tax ID, Registration Number, Passport, Digital Currency Address, etc.) |
| vessels | 1,480 | IMO coverage: 99.4%, Flag: 97.5%, Vessel type: 93.1% |
| entity_relationships | 7,704 | All "linked_to" type, extracted from "Linked To:" in remarks |

### How Compliance Analysts Use It

- **Transaction screening**: "Is this counterparty on the SDN list?"
- **50% Rule analysis**: "Entity X is not listed, but is it owned 50%+ by someone who is?" (traced via `entity_relationships`)
- **Vessel screening**: "Is this vessel (by IMO number) designated?" (critical for oil price cap enforcement)
- **Secondary sanctions exposure**: "Would my European bank face secondary sanctions risk?" (identified in remarks)
- **Alias matching**: "Could this party be using an alternate name?" (24,665 aliases enable fuzzy matching)
- **Digital currency screening**: 519+ cryptocurrency wallet addresses designated

### Source Format

Four headerless CSV files (comma-delimited):

| File | Content |
|------|---------|
| `sdn.csv` | Main records: ent_num, name, type, program, title, vessel fields, remarks |
| `add.csv` | Addresses linked by ent_num |
| `alt.csv` | Alternate names (aliases) linked by ent_num |
| `sdn_comments.csv` | Extended remarks/comments linked by ent_num |

The parser uses extensive regex extraction from the remarks field to pull DOBs, nationalities, vessel data (IMO/MMSI/build year), 27+ identifier types, and "Linked To" relationship references.

### Refresh Rationale

**Daily**. Designations take legal effect immediately upon publication. A bank that processes a blocked transaction even one day after designation faces strict liability. The 48-hour maximum staleness target is a regulatory necessity.

---

## OFAC Non-SDN Consolidated List

### What It Is

The Non-SDN Consolidated List aggregates persons and entities subject to **non-blocking** sanctions authorities. Unlike the SDN list (where all property is blocked), Non-SDN entries face specific, narrower restrictions depending on the program. This includes sectoral sanctions (debt/equity restrictions), Chinese Military-Industrial Complex (CMIC) designations, and other targeted measures.

**Issuing authority**: OFAC, US Department of the Treasury

**Legal framework**: Executive Orders imposing restrictions short of full blocking:
- EO 13662 (Sectoral Sanctions Identifications / SSI — debt/equity restrictions on Russian financial/energy/defense sectors)
- EO 14024 (Russia — certain non-blocking designations)
- EO 13959/14032 (CMIC — Chinese Military-Industrial Complex companies)
- NS-PLC (Palestine Liberation Committee)

**Consequence of designation**: Specific, limited restrictions. For example, US financial institutions cannot provide new debt of longer than 14 days maturity to a Directive 1 entity — but other transactions may be permissible. More nuanced than the binary blocked/not-blocked of the SDN list.

### Entity Composition

| Entity Type | Count | % of Total |
|-------------|-------|-----------|
| entity | 363 | 82.1% |
| individual | 79 | 17.9% |
| **Total** | **442** | 100% |

### Sanctions Programs

| Program Code | Records | Meaning |
|-------------|---------|---------|
| UKRAINE-EO13662 | 286 | Sectoral Sanctions — Russian financial/energy/defense (Directives 1-4) |
| RUSSIA-EO14024 | 93 | Russia-related non-blocking designations |
| NS-PLC | 78 | Palestine Liberation Committee |
| CMIC-EO13959 | 68 | Chinese Military-Industrial Complex |
| Others | 7 | SDGT, Venezuela, etc. |

Russia/Ukraine dominates: 85.7% of all Non-SDN entries.

### Key Difference from SDN

The Non-SDN list requires understanding **which Directive** applies:
- **Directive 1**: No new debt > 14 days maturity (financial sector)
- **Directive 2**: No new debt > 30 days maturity (energy sector)
- **Directive 3**: No new debt > 30 days or new equity (Russian defense sector)
- **Directive 4**: No goods/services for deepwater, Arctic, or shale projects

The Directive is specified in the remarks field and determines the exact scope of the prohibition.

### Related Records

| Table | Records | Notes |
|-------|---------|-------|
| entity_aliases | 1,144 | ~2.6 per entity (Russian corporate names have many variants) |
| entity_addresses | 522 | 88% coverage |
| entity_identifiers | 712 | Registration Number, Tax ID, Government Gazette Number, SWIFT/BIC |
| entity_relationships | 278 | All "linked_to" type |

### How Compliance Analysts Use It

- **Directive determination**: "This entity is on the SSI list — WHICH directive applies? What specifically is restricted?"
- **CMIC screening**: "Is this Chinese company on the CMIC list? Can we trade its securities?"
- **Escalation monitoring**: "Is this entity on Non-SDN only, or has it been escalated to SDN (full blocking)?"
- **50% Rule**: Ownership-based restrictions flow to Non-SDN subsidiaries too

### Source Format

Same 4-file CSV structure as SDN (`cons_prim.csv`, `cons_add.csv`, `cons_alt.csv`, `cons_comments.csv`). The parser reuses all parsing logic from `ofac_sdn.py`.

### Refresh Rationale

**Daily**. Same immediate-effect rationale as SDN, though in practice the Non-SDN list changes less frequently (mostly batch updates during new sanctions packages).

---

## EU Consolidated Financial Sanctions List

### What It Is

The EU's comprehensive list of all persons, groups, and entities subject to EU financial sanctions (primarily **asset freezes**). It consolidates designations from multiple EU Council Regulations into a single XML file. Published by the European Commission.

**Issuing authority**: Council of the European Union (designates), European Commission (publishes the consolidated list)

**Legal framework**: Multiple EU Council Regulations:
- **Reg. 269/2014** — Individual asset freeze designations (Russia/Ukraine)
- **Reg. 833/2014** — Sectoral measures (the regulation itself is not a designation list, but some entities are designated under implementing regulations)
- Country-specific regulations (Syria, Iran, DPRK, Libya, Belarus, etc.)
- EU counter-terrorism measures

**Consequence of designation**: Asset freeze. EU member state financial institutions must freeze all funds and economic resources belonging to, owned, held, or controlled by listed persons. No funds may be made available to them, directly or indirectly.

### Entity Composition

| Entity Type | Count | % of Total |
|-------------|-------|-----------|
| individual | 4,410 | 73.5% |
| entity | 1,586 | 26.5% |
| **Total** | **5,996** | 100% |

The EU list does not have distinct "vessel" or "aircraft" entity types. Vessels appear as entities with IMO identification documents attached (35 records).

### Programme Codes (Top Regimes)

| Programme | Records | Regime |
|-----------|---------|--------|
| UKR | 2,718 | Ukraine/Russia (Reg. 269/2014) |
| IRN | 711 | Iran |
| SYR | 380 | Syria |
| BLR | 372 | Belarus |
| TAQA | 344 | Counter-terrorism (Al-Qaeda/ISIL) |
| PRK | 255 | North Korea |
| HR | 170 | Human rights violations |
| AFG | 140 | Afghanistan |
| MMR | 128 | Myanmar |
| COD | 86 | Democratic Republic of Congo |

Total unique programme codes: **34**. Ukraine/Russia-related entries (UKR + RUS + RUSDA) account for 47.9% of all designations.

### Legal Basis (EU-Specific)

Unlike OFAC which uses program codes, the EU provides specific regulation references for each designation stored in the `legal_basis` field. Coverage: 99.7%. There are **447 distinct regulation references** — reflecting the EU's practice of publishing a new implementing regulation with each designation round.

### Field Coverage

| Field | Coverage | Compliance Significance |
|-------|----------|------------------------|
| `primary_name` | 100% | Favors English "strong" names from the XML |
| `programs` | 100% | Programme/regime code |
| `legal_basis` | 99.7% | Specific EU regulation reference — required for license applications |
| `date_of_birth` | 84.3% of individuals | From structured XML elements |
| `nationality` | 59.3% of individuals | Critical for Art. 5b (applies to Russian nationals regardless of residence) |
| `list_date` | 90.3% | When the entity was first designated |
| `remarks` | 11.6% | Much sparser than OFAC (98.2%) |

### Related Records

| Table | Records | Notes |
|-------|---------|-------|
| entity_aliases | 24,222 | ~4.0 per entity — EU provides names in multiple European languages |
| entity_addresses | 2,443 | 31.1% coverage |
| entity_identifiers | 2,615 | Registration Number, Passport, Fiscal Code, IMO |
| entity_relationships | 0 | Parser does not currently extract relationships from EU XML |

The high alias count (24,222 for only 5,996 entities vs. SDN's 24,665 for 18,959) is because the EU XML provides name variants in multiple languages (EN, FR, DE, RU transliterated, BG, etc.) for use by compliance teams across all 27 member states.

### How Compliance Analysts Use It

- **Asset freeze compliance**: "Is this customer/counterparty on the EU sanctions list?"
- **Programme identification**: "Under which EU regime is this entity sanctioned?" (determines available derogations and licensing authority)
- **Legal basis determination**: "What specific Council Regulation designated this entity?" (required for regulatory filings)
- **Multi-language matching**: "This wire beneficiary name is in Cyrillic — does it match?" (multi-language aliases enable cross-script matching)
- **Nationality-based restrictions**: Under Reg. 833/2014 Art. 5b, certain prohibitions apply to ALL Russian nationals, not just designated ones
- **Designation timing**: "Was this entity sanctioned before our transaction date?" (`list_date`)
- **Cross-jurisdiction comparison**: "Is this entity sanctioned by both the EU and OFAC?"

### Source Format

Single XML file following the `http://eu.europa.ec/fpi/fsd/export` namespace schema. Each `<sanctionEntity>` contains structured sub-elements for names (with language tags), birthdates, citizenships, addresses, identifications, regulations, and remarks. The parser uses lxml with namespace-aware XPath.

### Refresh Rationale

**Daily**. EU Council Implementing Regulations take effect upon Official Journal publication. The XML is typically updated within hours of new designations.

---

## OFAC Enforcement Actions

### What It Is

OFAC settlement agreements and penalty notices describing sanctions violations, penalty amounts, and compliance failures by companies. These are primary-source documents that analysts reference during investigations to understand precedent, risk factors, and penalty methodology.

**Issuing authority**: OFAC, US Department of the Treasury

**Pipeline**: PDF download (auto from OFAC website) -> PyMuPDF text extraction (Tesseract OCR fallback for scanned pages) -> chunking (~500 tokens, ~50 token overlap) -> BAAI/bge-m3 embedding -> storage in `document_chunks`

### Document Inventory

20 enforcement action PDFs covering major bank settlements and other notable cases:

| Document | Year | Chunks | Settlement Amount |
|----------|------|--------|-------------------|
| BNP Paribas SA | 2014 | 21 | $963M |
| Commerzbank AG | 2015 | 24 | $258M |
| UniCredit Group | 2019 | 5 | $611M |
| ING Bank N.V. | 2012 | 19 | $619M |
| HSBC Holdings | 2012 | 18 | $375M |
| Standard Chartered Bank | 2019 | 8 | $639M |
| Clearstream Banking SA | 2014 | 10 | $152M |
| Deutsche Bank AG | 2015 | 3 | $258M |
| Societe Generale SA | 2018 | 1 | $54M |
| Credit Suisse AG | 2009 | 3 | $536M |
| JPMorgan Chase Bank | 2011 | 7 | $88M |
| Barclays Bank PLC | 2010 | 13 | $176M |
| PayPal Inc. | 2015 | 10 | $7.7M |
| ZTE/Zhongxing Telecom | 2017 | 3 | $100M |
| Epsilon Electronics | 2018 | 3 | $4M |
| ExxonMobil | 2017 | 5 | $2M |
| General Electric | 2019 | 5 | $2.7M |
| BitGo Inc. | 2020 | 8 | $98K |
| Bittrex Inc. | 2022 | 18 | $24M |
| Apollo Aviation Group | 2019 | 23 | $210K |

**Total**: 207 chunks, 325K characters of text, all with 1024-dim bge-m3 embeddings.

Tags: `jurisdiction='US'`, `document_type='enforcement'`

### How Compliance Analysts Use It

- **Precedent research**: "Has any bank been fined for transactions with entity X?"
- **Penalty methodology**: "What factors did OFAC consider in determining the penalty amount?"
- **Compliance program benchmarking**: "What compliance failures led to enforcement actions?"
- **Risk assessment**: "What types of sanctions violations result in the largest penalties?"

### Refresh Rationale

**Monthly**. New enforcement actions are published as they occur. Monthly check captures new settlements.

---

## OFAC Guidance Documents

### What It Is

Interpretive guidance from OFAC that explains how to apply sanctions rules in specific situations. These are the documents analysts consult to understand policy intent beyond the raw legal text.

**Pipeline**: Same as enforcement — PDF download -> extraction -> chunking -> embedding -> `document_chunks`

### Document Inventory

| Document | Chunks | Description |
|----------|--------|-------------|
| OFAC Compliance Framework | 22 | The "Five Pillars" of an effective OFAC compliance program (management commitment, risk assessment, internal controls, testing/audit, training) |
| 50% Rule Guidance | 4 | How to determine whether an entity is blocked by virtue of 50%+ ownership by an SDN-listed person |

**Total**: 26 chunks, 40K characters.

Tags: `jurisdiction='US'`, `document_type='guidance'`

### How Compliance Analysts Use It

- **Compliance program design**: "What are the five pillars of an effective sanctions compliance program?"
- **50% Rule analysis**: "How do I calculate ownership for 50% Rule purposes when there are multiple blocked owners?"
- **Risk assessment**: "What factors should I consider in my OFAC risk assessment?"

### Refresh Rationale

**Quarterly**. OFAC guidance changes infrequently.

---

## Planned Sources (Not Yet Implemented)

### OFAC General Licenses

**What**: Pre-approved exemptions that authorize specific categories of transactions that would otherwise be blocked. Without these, the system can only say "this is blocked" — with them, it can say "this is blocked, BUT General License 8C authorizes wind-down transactions through [date]."

**Format**: PDF documents on the OFAC website. **Refresh**: Weekly.

**Compliance use**: Transaction authorization, wind-down planning, humanitarian exemptions.

### EU Regulation Text (Reg. 833/2014, Reg. 269/2014)

**What**: The full legal text of EU sanctions regulations. The entity list tells you WHO is sanctioned; the regulation text tells you WHAT is prohibited. Reg. 833/2014 imposes sectoral restrictions that apply to entire categories of activity (energy, trade, finance) regardless of whether a specific entity is individually designated.

**Format**: HTML/PDF from EUR-Lex. Structure-aware chunking required. **Refresh**: Weekly check, triggered on amendment.

**Compliance use**: "Can my bank provide investment services to a Russian national?", "What goods are restricted under the oil price cap?"

### Additional Guidance Sources

**What**: Further interpretive guidance beyond the two OFAC documents currently ingested.

**Sources**: OFAC FAQs (1,000+ Q&As), EU Commission FAQ on Russia sanctions, Bundesbank/BaFin circulars.

**Format**: HTML, PDF. **Refresh**: Monthly (OFAC/EU), quarterly (German authorities).

**Compliance use**: Procedural guidance, edge case interpretation, compliance program design.

---

## Cross-Source Relationships

### Dual-Jurisdiction Implications

European banks operating in USD markets must comply with **both** OFAC and EU sanctions simultaneously. Key differences:

| Dimension | OFAC | EU |
|-----------|------|-----|
| Designation identifier | Program codes (RUSSIA-EO14024) | Regulation references (Reg. 269/2014) |
| List structure | SDN (blocking) + Non-SDN (sectoral) separate | Single consolidated list for asset freezes; sectoral restrictions in regulation text |
| Name conventions | Latin script only | Multi-language (EN, FR, DE, RU transliterated, etc.) |
| Vessel handling | Explicit vessel entity type with IMO/MMSI fields | Vessels are entities with IMO identification documents |
| Relationship data | Extracted ("Linked To:") — 7,704 relationships | Not currently extracted |
| Sectoral restrictions | On-list (Non-SDN SSI directives) | In regulation text (Reg. 833/2014), not on the entity list |

### Known Overlaps

- Many Russian/Iranian/DPRK entities appear on both the SDN and EU lists under different authorities
- Same physical vessel can appear under multiple SDN entries (e.g., TASCA/IMO 9313149 designated under both Russia/Ukraine AND Iran programs)
- Entity identifiers (OFAC ent_num vs. EU euReferenceNumber) are completely different — cross-list matching requires fuzzy name matching plus identifier comparison

### Current Gaps

1. **No cross-list entity linking**: The same real-world entity across OFAC and EU records is not automatically matched
2. **EU relationships not extracted**: 50% Rule chain analysis is OFAC-only
3. **No regulation text ingested**: Cannot answer "what activities are prohibited" — only "who is designated"
4. **No General Licenses**: Cannot answer "what is authorized?" — only "what is blocked"

---

## Adding a New Source

### Structured Source (entities -> `sanctioned_entities`)

1. Create `new_source.py` in this directory
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

### Unstructured Source (documents -> `document_chunks`)

1. Create `new_source.py` in this directory
2. Define a manifest dict mapping document slugs to URLs, titles, and published dates
3. Use the shared infrastructure:
   - `pipeline.extraction.extract_pdf()` for PDF text extraction
   - `pipeline.chunking.text_chunker.TextChunker` for chunking
   - `pipeline.embeddings.EmbeddingModel` for embedding generation
   - `pipeline.chunk_store.store_document_chunks()` for storage (full-replace strategy)
4. Tag every chunk with `jurisdiction` (US/EU/DE) and `document_type` (enforcement/regulation/guidance/faq/general_license)

### Both types

5. Register in `runner.py`:
   ```python
   REGISTERED_SOURCES["new_source"] = ingest_new_source
   SOURCE_FILES["new_source"] = ["new_source/*.pdf"]
   ```
6. Add a script in `scripts/ingest_new_source.py`
7. Update this README's source inventory table
