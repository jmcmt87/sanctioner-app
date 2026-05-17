# Source Parsers

Each file in this directory handles ingestion for one sanctions data source. Structured parsers (OFAC SDN, Non-SDN, EU) normalize records into a standard dict format and call `upsert_entities()` to load into `sanctioned_entities`. Unstructured parsers (enforcement, guidance, general licenses, FAQs) extract PDF text, chunk it, generate embeddings, and store in `document_chunks` for RAG retrieval. All parsers log every run to `ingestion_log`.

---

## Source Inventory

| Source | File | Format | Refresh | Status |
| ------ | ---- | ------ | ------- | ------ |
| OFAC SDN List | `ofac_sdn.py` | CSV (4 files) | Daily | ✅ Implemented |
| OFAC Non-SDN Consolidated List | `ofac_nonsdn.py` | CSV (4 files) | Daily | ✅ Implemented |
| EU Consolidated Financial Sanctions List | `eu_sanctions.py` | XML (lxml) | Daily | ✅ Implemented |
| Enforcement Actions | `enforcement.py` | PDF (21 docs) | Monthly | ✅ Implemented |
| OFAC Guidance | `guidance.py` | PDF (2 docs) | Quarterly | ✅ Implemented |
| OFAC General Licenses | `general_licenses.py` | PDF (5 docs) | Weekly | ✅ Implemented |
| OFAC FAQ/Guidance | `ofac_faq.py` | PDF (3 docs) | Monthly | ✅ Implemented |
| EU Regulations (833/2014, 269/2014) | `eu_regulation.py` | HTML/PDF | Weekly check | ✅ Implemented |
| EU Commission FAQs on Reg. 833/2014 | — | PDF | Monthly | ❌ Not started |
| German Guidance (Bundesbank, BaFin, Ministry) | — | PDF | Quarterly | ❌ Not started |
| EU Derogation/Authorization Guidance | — | PDF/HTML | Quarterly | ❌ Not started |

**Embedding model:** Development uses `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions, 471MB, 50+ languages) for RAM-constrained environments. Production target is `BAAI/bge-m3` (1024 dimensions, 2.3GB) for higher retrieval precision. The model is configurable via `SSA_EMBEDDING_MODEL` and `SSA_EMBEDDING_DIM` environment variables. All chunks in the database must use the same embedding model — switching models triggers a full re-embed via the `backfill_embeddings.py` script.

---

## OFAC SDN List (Specially Designated Nationals and Blocked Persons)

### What It Is

The SDN List is the primary US sanctions enforcement tool. It identifies individuals, entities, vessels, and aircraft whose property and interests in property are **blocked** (frozen) by OFAC. US persons are generally prohibited from dealing with SDN-listed parties, and non-US persons face **secondary sanctions risk** for certain categories of transactions.

**Issuing authority:** Office of Foreign Assets Control (OFAC), US Department of the Treasury

**Legal framework:** International Emergency Economic Powers Act (IEEPA), plus multiple Executive Orders depending on the program (EO 14024 for Russia, EO 13846 for Iran, etc.)

**Consequence of designation:** Full blocking. All property and interests in property subject to US jurisdiction are frozen. Any US person (or person using the US financial system) that processes a transaction involving an SDN-listed party faces strict liability.

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

| Field | Coverage | Notes |
|-------|----------|-------|
| `primary_name` | 100% | Primary screening match field |
| `programs` | 100% | Determines which authority applies and what is prohibited. Parsed from `] [` delimited format. |
| `remarks` | 98.2% | Semi-structured text: identifiers, DOBs, relationships, secondary sanctions flags. Concatenated with `sdn_comments.csv` overflow file. |
| `date_of_birth` | 96.8% of individuals | Extracted from remarks via regex. Handles full dates (`10 Dec 1948`), year-only (`1962`), and multiple DOBs (`alt. DOB`). |
| `nationality` | 73.0% of individuals | Extracted from remarks. Higher than typical for OFAC data — 73% reflects successful regex extraction. |
| `country_of_registration` | 99.2% of entities | Derived from identifier country (Registration Number, Tax ID) with address country fallback. |
| `raw_record` | 100% | Full original record including concatenated remarks. |

### Related Records

| Table | Records | Notes |
|-------|---------|-------|
| entity_aliases | 24,665 | From `alt.csv` + inline `a.k.a.`/`f.k.a.` in remarks (deduplicated). 57.7% of individuals and 55.6% of entities have at least one alias. |
| entity_addresses | 21,522 | From `add.csv`. 83% of entities have at least one address. |
| entity_identifiers | 15,068+ | 41 identifier types extracted from remarks: Tax ID, Registration Number, Passport, SWIFT/BIC, LEI, Digital Currency Addresses (788 across 18 crypto types), Phone Numbers, etc. |
| vessels | 1,480 | IMO: 99.4%, Flag: 97.5%, Vessel name: 100%, MMSI: 50.5%, Build year: 19.7%. 1:1 correspondence with vessel entity_type records. |
| entity_relationships | 7,704 | All `linked_to` type, extracted from `Linked To:` pattern in remarks and resolved to entity records. |

### Parsing Details

**Comments file concatenation:** The main entity file (`sdn.csv`) has a character limit on the remarks field. Overflow text continues in `sdn_comments.csv`. The parser concatenates these before processing remarks. Critical because overflow contains aliases (e.g., Sovcomflot's `a.k.a. 'SCF'`), relationship links (e.g., `Linked To: LAZARUS GROUP`), and identifiers (Tax IDs, Registration Numbers, digital currency addresses).

**Entity type mapping:** OFAC only populates entity_type for individuals. Organizations have `-0-` (OFAC's null placeholder). The parser maps: `individual` → `individual`, `-0-` with vessel indicators → `vessel`, `-0-` with aircraft indicators → `aircraft`, everything else → `entity`.

**`-0-` handling:** All occurrences of `-0-` across all CSV files are replaced with NULL.

**OCR text cleaning:** Applied to all extracted text — removes garbled punctuation sequences, fixes spaced-out OCR headers (`W A S H I N G T O N` → `WASHINGTON`), collapses redundant whitespace.

### How Compliance Analysts Use It

- **Transaction screening:** "Is this counterparty on the SDN list?"
- **50% Rule analysis:** "Entity X is not listed, but is it owned 50%+ by someone who is?" (traced via `entity_relationships`)
- **Vessel screening:** "Is this vessel (by IMO number) designated?" (critical for oil price cap enforcement)
- **Secondary sanctions exposure:** "Would my European bank face secondary sanctions risk?" (identified in remarks)
- **Alias matching:** "Could this party be using an alternate name?" (24,665 aliases enable fuzzy matching)
- **Digital currency screening:** 788 cryptocurrency wallet addresses designated across 18 currency types

### Source Format

Four headerless CSV files (comma-delimited):

| File | Content |
|------|---------|
| `sdn.csv` | Main records: ent_num, name, type, program, title, vessel fields, remarks |
| `add.csv` | Addresses linked by ent_num |
| `alt.csv` | Alternate names (aliases) linked by ent_num |
| `sdn_comments.csv` | Extended remarks overflow linked by ent_num |

### Refresh Rationale

**Daily.** Designations take legal effect immediately upon publication. A bank that processes a blocked transaction even one day after designation faces strict liability. The 48-hour maximum staleness target is a regulatory necessity.

---

## OFAC Non-SDN Consolidated List

### What It Is

The Non-SDN Consolidated List aggregates persons and entities subject to **non-blocking** sanctions authorities. Unlike the SDN list (where all property is blocked), Non-SDN entries face specific, narrower restrictions depending on the program. This includes sectoral sanctions (debt/equity restrictions), Chinese Military-Industrial Complex (CMIC) designations, and other targeted measures.

**Issuing authority:** OFAC, US Department of the Treasury

**Legal framework:** Executive Orders imposing restrictions short of full blocking:
- EO 13662 (Sectoral Sanctions Identifications / SSI — debt/equity restrictions on Russian financial/energy/defense sectors)
- EO 14024 (Russia — certain non-blocking designations)
- EO 13959/14032 (CMIC — Chinese Military-Industrial Complex companies)
- NS-PLC (Palestine Liberation Committee)

**Consequence of designation:** Specific, limited restrictions. For example, US financial institutions cannot provide new debt of longer than 14 days maturity to a Directive 1 entity — but other transactions may be permissible. More nuanced than the binary blocked/not-blocked of the SDN list.

### Entity Composition

| Entity Type | Count | % of Total |
|-------------|-------|-----------|
| entity | 363 | 82.1% |
| individual | 79 | 17.9% |
| **Total** | **442** | 100% |

### Sanctions Programs

| Program Code | Records | Meaning |
|-------------|---------|---------|
| UKRAINE-EO13662 | 286 | Sectoral Sanctions — Russian financial/energy/defense (Directives 1–4) |
| RUSSIA-EO14024 | 93 | Russia-related non-blocking designations |
| NS-PLC | 78 | Palestine Liberation Committee |
| CMIC-EO13959 | 68 | Chinese Military-Industrial Complex |
| Others | 7 | SDGT, Venezuela, etc. |

Russia/Ukraine dominates: 85.7% of all Non-SDN entries.

### Key Difference from SDN

The Non-SDN list requires understanding **which Directive** applies:
- **Directive 1:** No new debt > 14 days maturity (financial sector)
- **Directive 2:** No new debt > 30 days maturity (energy sector)
- **Directive 3:** No new debt > 30 days or new equity (Russian defense sector)
- **Directive 4:** No goods/services for deepwater, Arctic, or shale projects

The Directive is specified in the remarks field and determines the exact scope of the prohibition.

### Field Coverage

| Field | Coverage | Notes |
|-------|----------|-------|
| `primary_name` | 100% | |
| `programs` | 100% | |
| `remarks` | 100% | Concatenated with `cons_comments.csv` overflow file |
| `date_of_birth` | 93.7% of individuals | |
| `nationality` | 2.5% of individuals | Expected — Non-SDN is almost entirely entities, and the few individuals rarely have nationality in remarks |
| `country_of_registration` | 100% of entities | Derived from identifier/address country |
| `raw_record` | 100% | |

### Related Records

| Table | Records | Notes |
|-------|---------|-------|
| entity_aliases | 1,144 | ~2.6 per entity (Russian corporate names have many transliteration variants) |
| entity_addresses | 522 | 88% coverage |
| entity_identifiers | 712 | Registration Number, Tax ID, Government Gazette Number, SWIFT/BIC, LEI |
| entity_relationships | 278 | All `linked_to` type |

### Dual-Listed Entities

Several major Russian banks and energy companies appear on BOTH the SDN and Non-SDN lists (e.g., VTB Bank, Sberbank, Gazprombank, Rosneft). This reflects their real-world status: originally designated on the Non-SDN/SSI list under sectoral sanctions, later elevated to the full SDN list as sanctions escalated post-2022. Both records are retained because the legal consequences differ — SDN means full blocking, Non-SDN means directive-specific restrictions. Analysts need to see both.

### How Compliance Analysts Use It

- **Directive determination:** "This entity is on the SSI list — WHICH directive applies? What specifically is restricted?"
- **CMIC screening:** "Is this Chinese company on the CMIC list? Can we trade its securities?"
- **Escalation monitoring:** "Is this entity on Non-SDN only, or has it been escalated to SDN (full blocking)?"
- **50% Rule:** Ownership-based restrictions flow to Non-SDN subsidiaries too

### Source Format

Same 4-file CSV structure as SDN (`cons_prim.csv`, `cons_add.csv`, `cons_alt.csv`, `cons_comments.csv`). The parser reuses all parsing logic from `ofac_sdn.py`.

### Refresh Rationale

**Daily.** Same immediate-effect rationale as SDN, though in practice the Non-SDN list changes less frequently (mostly batch updates during new sanctions packages).

---

## EU Consolidated Financial Sanctions List

### What It Is

The EU's comprehensive list of all persons, groups, and entities subject to EU financial sanctions (primarily **asset freezes**). It consolidates designations from multiple EU Council Regulations into a single XML file. Published by the European Commission's Foreign Policy Instruments Service (FPI).

**Issuing authority:** Council of the European Union (designates), European Commission (publishes the consolidated list)

**Legal framework:** Multiple EU Council Regulations:
- **Reg. 269/2014** — Individual asset freeze designations (Russia/Ukraine)
- **Reg. 833/2014** — Sectoral measures (implementing regulations designate specific entities)
- Country-specific regulations (Syria, Iran, DPRK, Libya, Belarus, etc.)
- EU counter-terrorism measures

**Consequence of designation:** Asset freeze. EU member state financial institutions must freeze all funds and economic resources belonging to, owned, held, or controlled by listed persons. No funds may be made available to them, directly or indirectly.

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

### Legal Basis

The `legal_basis` field stores both the specific implementing regulation from the EU XML (e.g., `Reg. 2024/1488`) and the enriched parent framework regulation derived from the programme code mapping (e.g., `Reg. 269/2014`, `Reg. 833/2014`). This dual approach ensures analysts can query by either the specific implementing regulation or the parent framework regulation they typically reference.

Coverage: 99.7%. There are **447 distinct implementing regulation references** plus the parent framework regulations added by enrichment.

**Programme-to-parent-regulation mapping** (applied during parsing):

| Programme | Parent Regulation(s) |
|-----------|---------------------|
| UKR | Reg. 269/2014, Reg. 833/2014 |
| RUS | Reg. 269/2014 |
| RUSDA | Reg. 833/2014 |
| IRN | Reg. 267/2012 |
| SYR | Reg. 36/2012 |
| BLR | Reg. 765/2006 |
| PRK | Reg. 329/2007 |
| TAQA | Reg. 2580/2001 |
| AFG | Reg. 753/2011 |
| Others | See parser source for complete mapping |

### Field Coverage

| Field | Coverage | Notes |
|-------|----------|-------|
| `primary_name` | 100% | Favors English "strong" names from the XML `wholeName` attribute |
| `programs` | 100% | Programme/regime code from XML `programme` attribute |
| `legal_basis` | 99.7% | Implementing regulation + enriched parent regulation |
| `date_of_birth` | 84.3% of individuals | From structured XML `<birthdate>` elements. Parsed as naive date (no timezone). |
| `nationality` | 59.3% of individuals | From XML `<citizenship>` elements. Coverage varies by programme: TAQA 94.5%, AFG 91.1%, UKR 48.2%. Lower UKR coverage is a **source data limitation**, not a parser bug — confirmed by inspecting raw_record for UKR individuals with null nationality. Birth country (in `<birthdate>` element) is correctly NOT conflated with nationality. |
| `country_of_registration` | 87.4% of entities | Derived from registration-type identifier country, then address country fallback. Not a native XML field. |
| `list_date` | 90.3% | Designation date from XML |
| `remarks` | 28.8% | Populated from `function` field in `<nameAlias>` elements where substantive descriptions exist (>50 chars). EU XML does not have a free-text remarks field comparable to OFAC. |
| `raw_record` | 100% | Full parsed XML data including all nested elements |

### Related Records

| Table | Records | Notes |
|-------|---------|-------|
| entity_aliases | 24,222 | ~4.0 per entity — EU provides names in multiple European languages (EN, FR, DE, RU transliterated, BG, etc.) |
| entity_addresses | 2,443 | 31.1% coverage |
| entity_identifiers | 2,615 | Registration Number (603), Passport (593), Fiscal Code (488), National ID (229), Tax ID (125), IMO (35), SWIFT/BIC (9) |
| entity_relationships | 0 | EU XML relationship extraction not yet implemented. Planned for v2. |

### Parsing Details

**Nationality vs. birth country:** The EU XML provides `<citizenship>` elements (nationality) and `<birthdate>` elements with birth location (place of birth). These are separate data elements. The parser extracts citizenship into `nationality` and birth country into raw_record metadata. Born in Russia does not mean Russian national — this distinction is legally critical under Art. 5b of Reg. 833/2014 which applies to Russian nationals regardless of residence.

**Date of birth timezone handling:** DOB is parsed as a naive `date` from the XML's structured `dayOfMonth`/`monthOfYear`/`year` attributes — no timezone interpretation. Earlier versions had a +1 day shift caused by CET timezone conversion; this was identified and fixed.

**Function field preservation:** The `function` attribute on `<nameAlias>` elements sometimes contains entity descriptions (e.g., "LLC Gazpromneft Marine Bunker Limited is a Russian shipping company... It manages tankers that transport crude oil or petroleum products"). These are preserved in the `remarks` field when substantive (>50 characters).

### How Compliance Analysts Use It

- **Asset freeze compliance:** "Is this customer/counterparty on the EU sanctions list?"
- **Programme identification:** "Under which EU regime is this entity sanctioned?" (determines available derogations and licensing authority)
- **Legal basis determination:** "What specific Council Regulation designated this entity?" (required for regulatory filings)
- **Parent regulation queries:** "Show me all entities designated under Reg. 269/2014" (enabled by legal basis enrichment)
- **Multi-language matching:** "This wire beneficiary name is in Cyrillic — does it match?" (multi-language aliases enable cross-script matching)
- **Nationality-based restrictions:** Under Reg. 833/2014 Art. 5b, certain prohibitions apply to ALL Russian nationals, not just designated ones
- **Designation timing:** "Was this entity sanctioned before our transaction date?" (`list_date`)
- **Cross-jurisdiction comparison:** "Is this entity sanctioned by both the EU and OFAC?"

### Source Format

Single XML file following the `http://eu.europa.ec/fpi/fsd/export` namespace schema. Each `<sanctionEntity>` contains structured sub-elements for names (with language tags), birthdates, citizenships, addresses, identifications, regulations, and remarks. The parser uses lxml with namespace-aware XPath. The `generationDate` attribute on the root `<export>` element provides the data vintage timestamp.

### Refresh Rationale

**Daily.** EU Council Implementing Regulations take effect upon Official Journal publication. The XML is typically updated within hours of new designations.

---

## OFAC Enforcement Actions

### What It Is

OFAC settlement agreements and penalty notices describing sanctions violations, penalty amounts, and compliance failures by companies. These are primary-source documents that analysts reference during investigations to understand precedent, risk factors, and penalty methodology.

**Issuing authority:** OFAC, US Department of the Treasury

**Pipeline:** PDF download (auto from OFAC website) → PyMuPDF text extraction (Tesseract OCR fallback for scanned pages) → OCR text cleaning → chunking (~500 tokens, ~50 token overlap) → BAAI/bge-m3 embedding → storage in `document_chunks`

### Document Inventory

21 enforcement action PDFs covering major bank settlements and other notable cases:

| Document | Year | Chunks | Settlement Amount |
|----------|------|--------|-------------------|
| Standard Chartered Bank | 2019 | 36 | $639M |
| UniCredit Bank AG | 2019 | 35 | $611M |
| Zhongxing Telecom (ZTE) | 2017 | 25 | $100M |
| Commerzbank AG | 2015 | 24 | $258M |
| Apollo Aviation Group | 2019 | 23 | $210K |
| BNP Paribas SA | 2014 | 21 | $963M |
| ING Bank N.V. | 2012 | 19 | $619M |
| HSBC Holdings | 2012 | 18 | $375M |
| Bittrex Inc. | 2022 | 18 | $24M |
| Societe Generale SA | 2018 | 17 | $54M |
| Barclays Bank PLC | 2010 | 13 | $176M |
| PayPal Inc. | 2015 | 10 | $7.7M |
| Clearstream Banking SA | 2014 | 10 | $152M |
| Deutsche Bank Trust Co. | 2020 | 9 | N/A |
| Bittrex Inc. | 2022 | 9 | $24M |
| BitGo Inc. | 2020 | 8 | $98K |
| JPMorgan Chase Bank | 2011 | 7 | $88M |
| ExxonMobil | 2017 | 6 | $2M |
| General Electric | 2019 | 5 | $2.7M |
| 50% Rule Guidance | 2014 | 4 | N/A |
| Epsilon Electronics | 2018 | 3 | $4M |
| Deutsche Bank AG | 2015 | 3 | $258M |
| Credit Suisse AG | 2009 | 3 | $536M |

**Total:** 286 chunks, 100% embedding coverage, 0 OCR artifacts.

Tags: `jurisdiction='US'`, `document_type='enforcement'`

### Text Quality

OCR text cleaning is applied during extraction:
- Removes garbled punctuation sequences (`[^\w\s]{3,}`)
- Fixes spaced-out OCR headers (`O F A C` → `OFAC`)
- Collapses redundant whitespace/newlines
- Post-cleaning verification: 0 chunks with OCR artifacts

Content validation during download: if expected entity keyword (e.g., "ING" for ING settlement) is not found in extracted text, the file is flagged for manual review. This catches mislabeled PDFs (e.g., the original ING PDF was serving UniCredit content from OFAC's website).

### How Compliance Analysts Use It

- **Precedent research:** "Has any bank been fined for transactions with entity X?"
- **Penalty methodology:** "What factors did OFAC consider in determining the penalty amount?"
- **Compliance program benchmarking:** "What compliance failures led to enforcement actions?"
- **Risk assessment:** "What types of sanctions violations result in the largest penalties?"
- **Comparative analysis:** "How did Commerzbank's violations differ from BNP Paribas's?"

### Refresh Rationale

**Monthly.** New enforcement actions are published as they occur. Monthly check captures new settlements.

---

## OFAC Guidance Documents

### What It Is

Interpretive guidance from OFAC that explains how to apply sanctions rules in specific situations. These are the documents analysts consult to understand policy intent beyond the raw legal text.

**Pipeline:** Same as enforcement — PDF download → extraction → OCR cleaning → chunking → embedding → `document_chunks`

### Document Inventory

| Document | Chunks | Description |
|----------|--------|-------------|
| OFAC Compliance Framework | 22 | The "Five Pillars" of an effective OFAC compliance program (management commitment, risk assessment, internal controls, testing/audit, training) |
| 50% Rule Guidance | 4 | Revised guidance (August 2014) on determining whether an entity is blocked by virtue of 50%+ ownership by an SDN-listed person |

**Total:** 26 chunks, 100% embedding coverage.

Tags: `jurisdiction='US'`, `document_type='guidance'`

### How Compliance Analysts Use It

- **Compliance program design:** "What are the five pillars of an effective sanctions compliance program?"
- **50% Rule analysis:** "How do I calculate ownership for 50% Rule purposes when there are multiple blocked owners?"
- **Risk assessment:** "What factors should I consider in my OFAC risk assessment?"

### Refresh Rationale

**Quarterly.** OFAC guidance changes infrequently.

---

## OFAC General Licenses

### What It Is

General Licenses are pre-approved authorizations that allow specific categories of transactions that would otherwise be blocked by sanctions. They are critical for answering "can we do this?" questions — without them, the tool can only say what is blocked, not what is authorized.

**Pipeline:** PDF download → extraction → OCR cleaning → chunking → embedding → `document_chunks`

### Document Inventory

| Document | Chunks | Description |
|----------|--------|-------------|
| General License 8K | varies | Russia-related wind-down authorizations |
| General License 13A | varies | Russia-related energy sector authorizations |
| General License 25F | varies | Russia-related agricultural/medical transactions |
| General License 44 | varies | Russia-related authorizations |
| General License 4C | varies | Russia-related authorizations |

**Total:** 18 chunks across 5 documents, 100% embedding coverage.

Tags: `jurisdiction='US'`, `document_type='general_license'`

### How Compliance Analysts Use It

- **Transaction authorization:** "Is this transaction type covered by an existing General License?"
- **Wind-down planning:** "What activities are authorized during the wind-down period?"
- **Humanitarian exemptions:** "Can we process payments for food/medicine to a sanctioned jurisdiction?"
- **Client advisory:** "Can we tell our client that this specific transaction is authorized?"

### Refresh Rationale

**Weekly.** New General Licenses are issued periodically, often in response to policy changes. Weekly check is sufficient, but newly issued GLs should trigger manual review.

---

## OFAC FAQ / Additional Guidance

### What It Is

Additional OFAC guidance documents covering specific compliance topics. Published as PDFs on the OFAC website.

**Note:** OFAC's full FAQ database (~1,200+ Q&As) is HTML-based and not yet ingested. The current ingestion covers PDF guidance documents that address frequently asked compliance questions.

**Pipeline:** PDF download → extraction → OCR cleaning → chunking → embedding → `document_chunks`

### Document Inventory

| Document | Chunks | Description |
|----------|--------|-------------|
| FFI Sanctions Guidance | varies | Foreign Financial Institution sanctions guidance |
| Food Security Fact Sheet | varies | Guidance on food/agriculture-related sanctions exemptions |
| Russia Compliance Alert | varies | Compliance advisory on Russia sanctions evasion patterns |

**Total:** 40 chunks across 3 documents, 100% embedding coverage.

Tags: `jurisdiction='US'`, `document_type='faq'`

### How Compliance Analysts Use It

- **Sector-specific guidance:** "What are the sanctions rules for agricultural transactions?"
- **Evasion patterns:** "What sanctions circumvention red flags should I look for?"
- **FFI obligations:** "What due diligence must foreign financial institutions perform?"

### Refresh Rationale

**Monthly.** OFAC periodically issues new guidance documents and compliance alerts.

---

## EU Regulations (833/2014 and 269/2014)

### What It Is

The full legal text of EU sanctions regulations — the documents that describe WHAT is prohibited, as opposed to the entity list which describes WHO is designated. These are the core regulatory documents that analysts reference daily for interpretation questions.

- **Reg. 833/2014** (Russia sectoral sanctions): ~734 pages covering trade restrictions, financial restrictions (deposit caps, securities prohibitions), energy restrictions (oil price cap, LNG), anti-circumvention provisions, and exemptions. Amended 20+ times since 2014. The consolidated version from EUR-Lex is the source of truth.
- **Reg. 269/2014** (Individual/entity asset freeze designations): Includes the regulation framework plus annexes with listing justifications for every designated individual and entity — the Council's stated reasons for each designation.

**Pipeline:** HTML/PDF download from EUR-Lex → structure-aware chunking (article-boundary splitting via `RegulationChunker`) → embedding → `document_chunks`

### Document Inventory

| Document | Articles | Chunks | Description |
|----------|----------|--------|-------------|
| Reg. 833/2014 (consolidated) | 809 | 1,190 | Russia sectoral sanctions — trade, finance, energy, anti-circumvention |
| Reg. 269/2014 (consolidated) | varies | 1,420 | Individual/entity asset freeze framework + listing justification annexes |

**Total:** 2,610 chunks across 2 regulations, 100% embedding coverage.

Tags: `jurisdiction='EU'`, `document_type='regulation'`

### Structure-Aware Chunking

The `RegulationChunker` splits at article boundaries rather than using generic text splitting. Each chunk is tagged with the appropriate `article_reference` (e.g., `Article 5b(1)`, `Article 3n(4)`), enabling metadata-filtered retrieval — an analyst asking about Article 5b gets chunks from that specific article, not semantically similar text from unrelated articles.

**Critical article validation:** Post-ingestion verification confirms that key articles of Reg. 833/2014 are represented in the chunks: Articles 3a, 3m, 3n, 5, 5a, 5aa, 5b, 5e, 5f, 5g, 5h, 5k, 5n, 11, 12.

The high chunk count for Reg. 269/2014 (1,420) reflects its annexes, which contain listing justifications for every designated person and entity — valuable for "why was this person/entity sanctioned?" queries that the structured entity list cannot answer.

### How Compliance Analysts Use It

- **Regulation interpretation:** "What are the deposit limits under Article 5b?"
- **Activity restrictions:** "Can my bank provide investment services to a Russian entity?"
- **Trade restrictions:** "What goods are covered by the oil price cap under Article 3n?"
- **Anti-circumvention:** "What does Article 12 say about circumvention?"
- **Exemptions:** "Are there exemptions for humanitarian transactions?"
- **Designation reasoning:** "Why was this entity sanctioned under Reg. 269/2014?" (from annexes)

### Refresh Rationale

**Weekly automated check.** Amendments are published via EU Council Decisions, typically every 2–4 months. The pipeline checks EUR-Lex weekly for new consolidated versions and alerts for re-ingestion.

---

## Database Summary (Current State as of 2026-05-17)

### Structured Data

| Source | Records | Entity Types |
|--------|---------|-------------|
| ofac_sdn | 18,959 | entity (9,670), individual (7,465), vessel (1,480), aircraft (344) |
| ofac_nonsdn | 442 | entity (363), individual (79) |
| eu_consolidated | 5,996 | individual (4,410), entity (1,586) |
| **Total** | **25,397** | |

### Unstructured Data (RAG Corpus)

Embedded with `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions, multilingual). Production target: `BAAI/bge-m3` (1024 dimensions).

| Document Type | Jurisdiction | Documents | Chunks | Embedding Coverage |
|--------------|-------------|-----------|--------|-------------------|
| enforcement | US | 21 | 286 | 100% |
| faq | US | 3 | 40 | 100% |
| general_license | US | 5 | 18 | 100% |
| guidance | US | 2 | 26 | 100% |
| regulation | EU | 2 | 2,610 | 100% |
| **Total** | | **33** | **2,980** | **100%** |

---

## Cross-Source Relationships

### Dual-Jurisdiction Implications

European banks operating in USD markets must comply with **both** OFAC and EU sanctions simultaneously. Key differences:

| Dimension | OFAC | EU |
|-----------|------|-----|
| Designation identifier | Program codes (RUSSIA-EO14024) | Regulation references (Reg. 269/2014) + programme codes |
| Legal basis | Programs only | Implementing regulation + enriched parent regulation |
| List structure | SDN (blocking) + Non-SDN (sectoral) separate | Single consolidated list for asset freezes; sectoral restrictions in regulation text |
| Name conventions | Latin script only | Multi-language (EN, FR, DE, RU transliterated, etc.) |
| Vessel handling | Explicit vessel entity type with IMO/MMSI fields | Vessels are entities with IMO identification documents |
| Relationship data | 7,982 `linked_to` relationships extracted | Not yet extracted (v2) |
| Sectoral restrictions | On-list (Non-SDN SSI directives in remarks) | In regulation text (Reg. 833/2014), not on the entity list |
| Remarks richness | Very rich (98.2% populated, semi-structured identifiers/relationships) | Sparse (28.8%, from function field descriptions) |
| Nationality coverage | 73% of individuals | 59.3% of individuals (source data limitation, varies by programme) |

### Known Gaps

1. **No cross-list entity linking:** The same real-world entity across OFAC and EU records is not automatically matched
2. **EU relationships not extracted:** 50% Rule chain analysis is OFAC-only
3. **EU/DE jurisdiction documents missing:** No EU Commission FAQs, no German guidance (Bundesbank, BaFin, Ministry)
4. **OFAC FAQs partially covered:** PDF guidance documents ingested, but the full HTML FAQ database (~1,200+ Q&As) not yet ingested
5. **Development embedding model:** Multilingual MiniLM (384-dim) is adequate for current corpus size but should be upgraded to bge-m3 (1024-dim) for production deployment on 16GB+ RAM hardware

---

## Adding a New Source

### Structured Source (entities → `sanctioned_entities`)

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

### Unstructured Source (documents → `document_chunks`)

1. Create `new_source.py` in this directory
2. Define a manifest dict mapping document slugs to URLs, titles, and published dates
3. Use the shared infrastructure:
   - `pipeline.extraction.extract_pdf()` for PDF text extraction (includes OCR cleaning)
   - `pipeline.chunking.text_chunker.TextChunker` for standard chunking
   - `pipeline.chunking.regulation_chunker.RegulationChunker` for article-aware regulation chunking
   - `pipeline.embeddings.EmbeddingModel` for embedding generation (reads model from `SSA_EMBEDDING_MODEL` env var)
   - `pipeline.chunk_store.store_document_chunks()` for storage (full-replace strategy, accepts None embeddings for two-pass ingestion)
4. Tag every chunk with `jurisdiction` (US/EU/DE) and `document_type` (enforcement/regulation/guidance/faq/general_license)
5. For large documents on RAM-constrained machines, use two-pass ingestion: set `SSA_SKIP_EMBEDDINGS=true` to store chunks with NULL embeddings, then run `scripts/backfill_embeddings.py` to embed in batches

### Both Types

6. Register in `runner.py`:
   ```python
   REGISTERED_SOURCES["new_source"] = ingest_new_source
   SOURCE_FILES["new_source"] = ["new_source/*.pdf"]
   ```
7. Add a script in `scripts/ingest_new_source.py`
8. Update this README's source inventory table