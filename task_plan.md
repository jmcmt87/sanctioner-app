# Task Plan — Sanctions Screening Assistant (v3)

## Overview

16-week development plan broken into 6 phases. Each task has an estimated effort, dependencies, and acceptance criteria. Tasks marked **[ESSENTIAL]** are MVP-critical. Tasks marked **[RECOMMENDED]** add quality but can be cut if time is tight. Tasks marked **[DOMAIN]** require input from the compliance expert.

**Timeline**: 16 weeks (Weeks 1–16), with buffer to 20 weeks if needed
**Hard deadline**: 9 December 2026
**Working assumption**: ~30–40 hours/week of development time using Claude Code

## Phase 1 — Foundation & Data Ingestion (Weeks 1–3)

**Goal**: Raw data flows from sources into PostgreSQL. Structured entities are queryable via SQL with relationship data. First batch of documents is chunked, embedded, and searchable via vector similarity.

### 1.1 Project Scaffolding

**1.1.1** Initialize repository structure **[ESSENTIAL]**
- Set up monorepo with `backend/`, `ingestion/`, `frontend/`, `infra/` directories
- Initialize Python projects with `pyproject.toml` (backend and ingestion as separate packages)
- Set up `docker-compose.yml` with PostgreSQL 16 + pgvector extension
- Create `.env.example` with all required environment variables
- Initialize alembic for migrations
- **Effort**: 0.5 day
- **Acceptance**: `docker-compose up` starts PostgreSQL with pgvector. Alembic can connect and run empty migration.

**1.1.2** Database schema — structured entity tables **[ESSENTIAL]**
- Create SQLAlchemy models for: `sanctioned_entities`, `entity_aliases`, `vessels`, `entity_addresses`, `entity_identifiers`, `entity_relationships`
- `sanctioned_entities` must include: `date_of_birth` (DATE), `nationality` (TEXT[]), `country_of_registration` (TEXT), `legal_basis` (TEXT[] — separate from programs, used for EU regulation references)
- `vessels` must include: `vessel_name` (TEXT — separate from parent entity name, vessels get renamed), `build_year` (INTEGER — age is a shadow fleet risk indicator)
- `entity_relationships`: `from_entity_id`, `to_entity_id`, `relationship_type`, `ownership_percentage`, `notes`, `source`. Critical for 50% Rule ownership chain tracing.
- Create alembic migration
- Add `ingestion_log` table for tracking data freshness
- **Effort**: 1.5 days
- **Depends on**: 1.1.1
- **Acceptance**: All tables created via migration. Can insert and query test records. Entity relationships can be queried bidirectionally.

**1.1.3** Database schema — vector store tables **[ESSENTIAL]**
- Create `document_chunks` table with pgvector column, tsvector column, metadata fields
- Create HNSW index on embedding column
- Create GIN index on tsvector column
- **Effort**: 0.5 day
- **Depends on**: 1.1.1
- **Acceptance**: Can insert a test vector and run similarity search. Full-text search index works.

**1.1.4** Configuration management **[ESSENTIAL]**
- Implement `pydantic-settings` config class with all env vars (DB connection, LLM config, S3 config, embedding model path)
- Set up structlog for JSON logging
- **Effort**: 0.5 day
- **Depends on**: 1.1.1
- **Acceptance**: Config loads from `.env`. Structured logs output to stdout.

### 1.2 Structured Data Ingestion

**1.2.1** OFAC SDN list ingestion **[ESSENTIAL]**
- Download SDN CSV (pipe-delimited) from OFAC website
- Parse entities, aliases, addresses, identifiers, and remarks
- Handle entity types: individuals, entities, vessels, aircraft
- Map to `sanctioned_entities` + child tables
- Extract `date_of_birth` and `nationality` for individuals (OFAC provides these in SDN data and add.csv)
- Extract `vessel_name`, `build_year` into `vessels` table alongside IMO/MMSI numbers
- Parse ownership/relationship references from remarks field into `entity_relationships` table where extractable
- Preserve OFAC entity sub-type (organization, government entity, etc.) in `raw_record` JSONB
- Implement upsert logic (compare by source + source_id)
- Log ingestion run to `ingestion_log`
- **Effort**: 3–4 days
- **Depends on**: 1.1.2
- **Gotchas**: SDN CSV has a non-standard pipe-delimited format with multiple related files (sdn.csv, add.csv, alt.csv, sdn_comments.csv). Vessel data is embedded within the entity list with entity_type='vessel'. Alternative names are in a separate file (alt.csv) linked by ent_num. Ownership info in remarks is semi-structured text — expect partial extraction, not 100% coverage.
- **Acceptance**: All ~12,000 SDN entries loaded. Aliases linked. Vessels extracted with IMO numbers and vessel_name. DOB/nationality populated for individuals. Known ownership relationships extracted. Can query by name, program, entity type, and nationality.

**1.2.2** EU Consolidated Financial Sanctions List ingestion **[ESSENTIAL]**
- Download EU list XML from European Commission
- Parse XML structure (entity nodes with name variants, addresses, identifiers, programs)
- Map to `sanctioned_entities` + child tables with source='eu_consolidated'
- Extract `date_of_birth`, `nationality` for individuals (EU XML has these as structured fields)
- Extract `country_of_registration` for entities where available
- Populate `legal_basis` array with EU regulation references (e.g., 'Reg. 269/2014')
- Extract entity relationships from EU XML relationship fields into `entity_relationships`
- Implement upsert logic
- **Effort**: 2–2.5 days
- **Depends on**: 1.1.2
- **Gotchas**: EU XML schema is different from OFAC CSV. Entity names may be in multiple languages. Programs field uses EU regulation references, not OFAC program codes. Nationality and DOB are more reliably structured in EU data than in OFAC.
- **Acceptance**: All ~4,000–6,000 EU entities loaded. DOB/nationality populated. Legal basis captured. Can query and distinguish from OFAC entries. Can filter by nationality.

**1.2.3** OFAC Non-SDN list ingestion **[RECOMMENDED]**
- Download and parse the Consolidated Non-SDN list (similar format to SDN)
- Map to `sanctioned_entities` with source='ofac_nonsdn'
- **Effort**: 0.5 day (reuse SDN parser with minor adjustments)
- **Depends on**: 1.2.1
- **Acceptance**: ~1,900 Non-SDN entries loaded.

**1.2.4** Incremental update logic for sanctions lists **[ESSENTIAL]**
- Implement hash-based comparison: hash each incoming record, compare against stored hash
- Detect additions, modifications, and removals
- Log deltas to ingestion_log (records_added, records_updated, records_removed)
- Store previous record version in raw_record JSONB for audit trail
- **Effort**: 1–1.5 days
- **Depends on**: 1.2.1, 1.2.2
- **Acceptance**: Re-running ingestion on unchanged data produces zero changes. Modifying one record in source correctly detects the delta.

**1.2.5** S3 integration for raw document storage **[ESSENTIAL]**
- Set up S3 bucket with prefix-based organization: `raw/ofac/sdn/`, `raw/eu/consolidated/`, `raw/enforcement/`, `raw/regulations/`, etc.
- Upload script to push source files to S3
- Download helper to fetch latest version from S3 before parsing
- **Effort**: 1 day
- **Depends on**: 1.1.4
- **Acceptance**: Source files stored in S3 with version timestamps. Ingestion pipeline reads from S3.

### 1.3 Unstructured Data Ingestion (First Batch)

**1.3.1** Embedding model setup **[ESSENTIAL]**
- Install and configure sentence-transformers
- Initial model: BAAI/bge-m3 (multilingual, 1024-dim, supports dense + sparse)
- Create embedding wrapper class with batch processing support
- Benchmark embedding speed on sample documents (target: understand throughput for planning)
- **Effort**: 0.5–1 day
- **Depends on**: 1.1.3
- **Acceptance**: Can embed a batch of text chunks and store in pgvector. Similarity search returns sensible results on test data.

**1.3.2** PDF extraction pipeline **[ESSENTIAL]**
- Evaluate extraction tools on sample enforcement PDFs: PyMuPDF (fitz) for text-based, Tesseract/easyOCR for scanned
- Build extraction wrapper that detects PDF type and routes accordingly
- Handle common issues: headers/footers, page numbers, table extraction, multi-column layouts
- **Effort**: 1.5–2 days
- **Depends on**: 1.1.4
- **Gotchas**: OFAC enforcement PDFs vary widely in quality. Some are clean text, some are scanned. Test on at least 5 different enforcement PDFs from different eras before committing to a single extraction approach.
- **[DOMAIN]**: Ask compliance expert to flag any PDFs that are known to be low-quality scans.
- **Acceptance**: Can extract clean text from 5+ sample enforcement PDFs. OCR fallback works for scanned documents.

**1.3.3** Text chunking — default strategy **[ESSENTIAL]**
- Implement RecursiveCharacterTextSplitter wrapper (~500 tokens, ~50 token overlap)
- Add metadata tagging per chunk: source_document, jurisdiction, document_type, published_date, chunk_index, ingestion_timestamp, data_vintage
- **Effort**: 0.5 day
- **Depends on**: 1.3.1
- **Acceptance**: Chunks are correctly sized. Metadata is complete on every chunk.

**1.3.4** Ingest first batch of enforcement PDFs **[ESSENTIAL]**
- Process ~20–30 enforcement PDFs (prioritize the major European bank settlements: Commerzbank, BNP Paribas, UniCredit, ING, HSBC, Standard Chartered, Clearstream)
- Extract text → chunk → embed → store in document_chunks
- Tag each with jurisdiction='US', document_type='enforcement'
- **Effort**: 1 day
- **Depends on**: 1.3.2, 1.3.3
- **Acceptance**: Chunks stored with correct metadata. Semantic search for "Iran violations bank penalty" returns relevant Commerzbank/BNP chunks.

**1.3.5** Ingest OFAC Compliance Framework + 50% Rule guidance **[ESSENTIAL]**
- Download and process the OFAC Compliance Framework PDF ("five pillars")
- Download and process the 50% Rule guidance PDF
- Chunk and embed with appropriate metadata
- **Effort**: 0.5 day
- **Depends on**: 1.3.2, 1.3.3
- **Acceptance**: Can retrieve relevant chunks for queries about compliance program elements or ownership-based blocking.

### Phase 1 Checkpoint

- [ ] PostgreSQL running with all entity tables (including relationships) and vector store tables
- [ ] OFAC SDN + EU Consolidated List loaded with DOB, nationality, legal basis, relationships
- [ ] Vessel records extracted and queryable by IMO number, with vessel_name and build_year
- [ ] Entity relationships populated where extractable from source data
- [ ] 20–30 enforcement PDFs chunked, embedded, and searchable
- [ ] OFAC Compliance Framework + 50% Rule in vector store
- [ ] Incremental update logic working for sanctions lists
- [ ] S3 bucket organized with raw source files
- [ ] Ingestion log tracking all runs

---

## Phase 2 — Agent Core & Retrieval (Weeks 4–6)

**Goal**: LangGraph agent preprocesses queries, classifies intent, routes to the correct data source, synthesizes cited responses, and formats output with data vintage and language handling. Single-turn queries only — conversation memory is deferred to Phase 3. Citation format locked with domain expert before synthesis prompt is built. Mistral API is the LLM during this phase.

### 2.1 LLM Integration

**2.1.1** LLM client abstraction **[ESSENTIAL]**
- Create a client wrapper that supports Mistral API, Ollama, and vLLM (all OpenAI-compatible)
- Configure via environment variables (base_url, model_name, api_key)
- Support streaming and non-streaming modes
- **Effort**: 0.5–1 day
- **Depends on**: 1.1.4
- **Acceptance**: Same code calls Mistral API and local Ollama with only env var changes.

### 2.2 Agent Orchestration

**2.2.1** LangGraph state schema **[ESSENTIAL]**
- Define the agent state: original_query, preprocessed_output (normalized_query, entities, sub_queries, source_language), classified_intent, sql_results, retrieved_docs, synthesized_response, formatted_response, citations, data_vintage_metadata
- Note: conversation_history will be added to the state schema in Phase 3 when memory is implemented
- **Effort**: 0.5 day
- **Depends on**: 2.1.1
- **Acceptance**: State schema defined with proper typing.

**2.2.2** preprocess_query node **[ESSENTIAL]**
- Single LLM call that normalizes raw analyst input before classification
- Language normalization: rewrite to English (preserve entity names as typed)
- Entity extraction: pull out entity names, vessel names, regulation references, article numbers into structured fields
- Query decomposition: split compound questions into atomic sub-queries with intent hints
- Spelling correction: fuzzy-match against a small dictionary of known entity names and regulatory terms
- Detect source language for response translation in format_response node
- Output schema: `{ original_query, normalized_query, entities[], regulations_referenced[], sub_queries[], source_language }`
- **Effort**: 1.5–2 days
- **Depends on**: 2.2.1, 2.1.1
- **Gotchas**: Analysts at German banks will write mixed DE/EN queries with internal jargon. "Check the 50% rule for this entity's sub" needs to become a structured query. The preprocessing prompt needs real examples — get 20+ messy real-world query examples from compliance expert.
- **[DOMAIN]**: Need examples of how analysts actually phrase queries in practice (mixed language, abbreviations, shorthand).
- **Acceptance**: Mixed-language compound query like "Ist Sovcomflot auf der SDN List und was sagt GL13?" produces correctly decomposed, English-normalized sub-queries with extracted entities.

**2.2.3** classify_query node **[ESSENTIAL]**
- LLM-based intent classification: entity_lookup | vessel_lookup | guidance_search | regulation_check | hybrid
- Receives clean structured input from preprocess_query, not raw user text
- Design classification prompt with examples for each intent type
- Include confidence score in output
- Add fallback logic for ambiguous queries (default to hybrid if confidence < threshold)
- **Effort**: 1.5–2 days
- **Depends on**: 2.2.2
- **[DOMAIN]**: Need 20+ example queries per intent type from compliance expert for the classification prompt and eval set.
- **Acceptance**: Correctly classifies >85% of preprocessed test queries. Ambiguous queries default to hybrid.

**2.2.4** execute_sql node — entity lookup **[ESSENTIAL]**
- Build SQL query generation for entity lookups: search by name (fuzzy), programs, entity_type, source list, nationality
- Use trigram similarity (pg_trgm) for fuzzy name matching
- Return structured entity data with all aliases, addresses, identifiers, DOB, nationality, country of registration
- Include related entities from `entity_relationships` table (ownership chains, subsidiaries)
- Include data_vintage in results
- **Effort**: 2–2.5 days
- **Depends on**: 2.2.1, Phase 1 entity tables
- **Gotchas**: Fuzzy matching is critical — analysts may use slightly different name spellings. pg_trgm with a similarity threshold of ~0.3 is a good starting point, but test against known entity name variations. Relationship traversal should be shallow (1 hop) for MVP — recursive ownership chain walking is a v2 feature.
- **Acceptance**: "Is Sovcomflot sanctioned?" returns the correct entity with all aliases, DOB (if individual), nationality, and known related entities. Fuzzy match handles typos and transliterations.

**2.2.5** execute_sql node — vessel lookup **[ESSENTIAL]**
- Extend SQL node to handle vessel-specific queries by IMO number, vessel name, or owning entity
- Return vessel_name, build_year, flag alongside IMO/MMSI
- Join vessels → sanctioned_entities → entity_relationships to show ownership chain
- **Effort**: 0.5–1 day
- **Depends on**: 2.2.4
- **Acceptance**: "What vessels are associated with Sovcomflot?" returns vessel list with vessel names, IMO numbers, build years, and linked entity data.

**2.2.6** retrieve_docs node — semantic search **[ESSENTIAL]**
- Implement pgvector similarity search with configurable top-k
- Add metadata filtering: filter by jurisdiction, document_type, date range
- Return chunks with full metadata (source, article_reference, data_vintage)
- **Effort**: 1 day
- **Depends on**: 2.2.1, Phase 1 vector store
- **Acceptance**: Semantic search for regulatory queries returns relevant chunks with proper metadata.

**2.2.7** retrieve_docs node — BM25 (full-text search) **[ESSENTIAL]**
- Implement PostgreSQL full-text search using tsvector/tsquery
- Support phrase matching and boolean queries
- **Effort**: 0.5–1 day
- **Depends on**: 2.2.6
- **Acceptance**: Searching "GL 13" returns the General License 13 document chunks. Keyword-heavy queries return precise matches.

**2.2.8** Ensemble retriever with Reciprocal Rank Fusion **[ESSENTIAL]**
- Combine semantic search + BM25 results using RRF
- Configurable weight between semantic and keyword scores
- Deduplicate results that appear in both result sets
- Return top-k merged results
- **Effort**: 1 day
- **Depends on**: 2.2.6, 2.2.7
- **Acceptance**: Hybrid search outperforms either method alone on a sample of mixed query types (measure manually with 10 queries).

**2.2.9** Define citation format **[ESSENTIAL]**
- Mock up 3 candidate citation formats (e.g., footnote-style, inline bracket, expandable reference)
- Each format should show: source document title, jurisdiction label (US/EU/DE), relevant passage excerpt, article reference where applicable, data vintage timestamp
- Send to compliance expert async for feedback — does not require a full session
- Lock the chosen format before building the synthesis prompt
- **Effort**: 0.5 day (plus async turnaround from domain expert)
- **[DOMAIN]**: Compliance expert selects preferred citation format. Key question: "Is this how you'd want to see sources referenced in an investigation?"
- **Acceptance**: Citation format agreed upon and documented. Synthesis prompt (2.2.10) will build against this format.

**2.2.10** synthesize node **[ESSENTIAL]**
- Design synthesis prompt: given query + retrieved context (SQL results and/or document chunks), generate a response with inline citations in the agreed format from 2.2.9
- Include data vintage timestamps in the response metadata
- Handle the dual-jurisdiction case: when results come from both OFAC and EU sources, clearly distinguish which jurisdiction each finding applies to
- Proactively reference applicable General Licenses or EU derogations when identifying blocked activities
- **Effort**: 2–3 days
- **Depends on**: 2.2.4–2.2.9
- **Acceptance**: Responses include inline citations in the locked format. Data vintage is present. Dual-jurisdiction queries clearly label US vs EU findings.

**2.2.11** format_response node **[ESSENTIAL]**
- Lightweight post-processing LLM call (or rule-based where possible)
- Enforce citation format consistency across all response types
- Add data vintage disclaimer per source consulted (e.g., "Based on OFAC SDN list as of 2026-05-07")
- Translate response to analyst's source language if they wrote in German (keep regulatory terms, entity names, and citations in original language)
- Flag when response draws from multiple jurisdictions
- **Effort**: 1–1.5 days
- **Depends on**: 2.2.10
- **Gotchas**: Some formatting (vintage disclaimer, jurisdiction flags) can be rule-based rather than LLM-based — don't burn an LLM call for things string templates can handle. Use LLM only for translation and natural language formatting.
- **Acceptance**: German query gets German response with English citations intact. Data vintage appears on every response. Citation format is consistent.

**2.2.12** LangGraph state machine wiring **[ESSENTIAL]**
- Wire all nodes into LangGraph graph: START → preprocess_query → classify_query → conditional routing → [execute_sql, retrieve_docs, or both] → synthesize → format_response → END
- Handle error states (SQL failure, empty retrieval, LLM timeout, preprocessing failure)
- Single-turn only — no conversation memory in this phase
- **Effort**: 1.5–2 days
- **Depends on**: 2.2.2–2.2.11
- **Acceptance**: End-to-end: raw mixed-language query in → preprocessed → classified → routed → data retrieved → cited response → formatted output. Each query is standalone.

### Phase 2 Checkpoint

- [ ] LangGraph agent end-to-end: raw query → preprocess → classify → route → retrieve/lookup → synthesize → format → output
- [ ] Preprocessing handles mixed DE/EN queries and compound question decomposition
- [ ] Entity lookup works with fuzzy matching, returns DOB/nationality/relationships
- [ ] Vessel lookup by IMO number and owner, includes build year and ownership chain
- [ ] Hybrid retrieval (BM25 + semantic) working
- [ ] Citation format locked with domain expert sign-off
- [ ] Response formatting includes data vintage and handles language translation
- [ ] Single-turn agent stable and testable

---

## Phase 3 — API Layer, Eval & Document Ingestion (Weeks 7–9)

**Goal**: FastAPI backend exposes the agent as a production-ready API with streaming support, conversation memory, and OpenAPI docs. Eval harness running. Key document sources ingested with structure-aware chunking where needed.

### 3.1 API Implementation

**3.1.1** Core query endpoint — POST /api/query **[ESSENTIAL]**
- Accepts: query text, optional filters (jurisdiction, document_type), conversation_id
- Returns: response text, citations array, data_vintage metadata, agent_trace (routing decision + sources consulted)
- Pydantic request/response schemas
- **Effort**: 1 day
- **Depends on**: Phase 2 agent
- **Acceptance**: Can call endpoint via curl/httpie and get a full cited response.

**3.1.2** Entity search endpoint — GET /api/entity-search **[ESSENTIAL]**
- Direct entity lookup bypassing the agent (for dedicated entity search UI)
- Parameters: name (fuzzy), source_list, entity_type, program, nationality
- Returns: paginated entity results with aliases, identifiers, DOB, nationality, relationships
- **Effort**: 1 day
- **Depends on**: Phase 1 entity tables
- **Acceptance**: Entity search returns structured results. Fuzzy matching works. Nationality filter works.

**3.1.3** Streaming endpoint — WebSocket /api/stream **[ESSENTIAL]**
- WebSocket connection for streaming LLM responses token by token
- Stream includes: partial response text, then final citations and metadata once complete
- Handle connection lifecycle: connect, stream, close, error
- **Effort**: 2–3 days
- **Depends on**: 3.1.1
- **Acceptance**: Frontend can connect via WebSocket, receive streaming tokens, and get final structured metadata.

**3.1.4** Data freshness endpoint — GET /api/data-status **[ESSENTIAL]**
- Returns current data vintage for each source (last ingestion timestamp, record counts)
- Highlights any sources that are stale beyond expected refresh cadence
- **Effort**: 0.5 day
- **Depends on**: Phase 1 ingestion_log table
- **Acceptance**: Endpoint returns a clear summary of data freshness per source.

**3.1.5** Conversation memory **[ESSENTIAL]**
- Store conversation history per session
- Support conversation_id for follow-up queries
- Implement ConversationBufferWindowMemory (window=5 messages)
- Extend LangGraph state schema with conversation_history field
- Inject memory into preprocess_query so follow-up questions resolve implicit references from prior turns
- **Effort**: 1.5–2 days
- **Depends on**: 3.1.1, Phase 2 agent (single-turn must be stable first)
- **Acceptance**: Follow-up questions in the same conversation use prior context. "What about under EU law?" following an OFAC query works correctly. Preprocessing resolves "that entity" to the entity discussed in the previous turn.

**3.1.6** Error handling and validation **[ESSENTIAL]**
- Global exception handler with structured error responses
- Input validation via Pydantic (max query length, allowed filter values)
- Rate limiting (basic, for demo protection)
- Request correlation IDs in logs
- **Effort**: 1 day
- **Depends on**: 3.1.1
- **Acceptance**: Invalid inputs return 422 with clear messages. Server errors return 500 with correlation ID. Logs are traceable.

**3.1.7** OpenAPI documentation **[ESSENTIAL]**
- Auto-generated via FastAPI (comes free with Pydantic schemas)
- Add descriptions, examples, and response schema documentation
- **Effort**: 0.5 day (mostly ensuring schemas have good docstrings)
- **Depends on**: 3.1.1–3.1.6
- **Acceptance**: Swagger UI at /docs is clear, complete, and testable.

### 3.2 Document Ingestion (Continued)

**3.2.1** Ingest OFAC General Licenses (Russia program) **[ESSENTIAL]**
- Download all active Russia-related General Licenses (~dozens of 1–2 page PDFs)
- Chunk and embed with metadata: document_type='general_license', specific GL number in article_reference
- **Effort**: 1 day
- **Depends on**: Phase 1 ingestion pipeline
- **Acceptance**: "What does GL 44 authorize?" returns relevant GL 44 chunks.

**3.2.2** Ingest OFAC FAQs **[ESSENTIAL]**
- Download OFAC FAQ page (HTML). Parse individual Q&A pairs.
- Each Q&A should ideally be its own chunk (they're typically short enough)
- Tag with topic categories if available
- **Effort**: 1–1.5 days
- **Depends on**: Phase 1 ingestion pipeline
- **Gotchas**: The OFAC FAQ page is one long HTML document with 1,200+ Q&As. You need to parse individual question-answer pairs, not chunk the whole page blindly.
- **Acceptance**: "What is the 50% rule?" returns relevant FAQ entries alongside the guidance document chunks.

**3.2.3** Ingest Reg. 833/2014 (consolidated version) **[ESSENTIAL]**
- Download consolidated version from EUR-Lex
- Implement structure-aware chunking: respect article boundaries
- Parse article/paragraph/sub-paragraph structure from EUR-Lex HTML/XML
- Each chunk tagged with article_reference (e.g., "Article 5b(1)")
- **Effort**: 2–3 days
- **Depends on**: Phase 1 chunking pipeline
- **[DOMAIN]**: Ask compliance expert which articles are most frequently referenced to prioritize testing.
- **Gotchas**: Article lengths vary enormously. Some are one paragraph, some are pages long. Long articles should be split at paragraph boundaries, not arbitrary character counts. EUR-Lex HTML/XML structure is not always clean — test parsing thoroughly before batch processing.
- **Acceptance**: "What are the deposit restrictions under EU sanctions?" retrieves relevant Article 5b chunks with correct article references.

**3.2.4** Ingest EU Commission FAQs on Reg. 833/2014 **[ESSENTIAL]**
- Download ~30+ topic-specific FAQ PDFs from European Commission
- Parse individual Q&A pairs where possible
- Tag with jurisdiction='EU', document_type='faq', and topic reference
- **Effort**: 1.5 days
- **Depends on**: Phase 1 ingestion pipeline
- **Acceptance**: EU-specific FAQ queries return relevant Commission guidance.

**3.2.5** Ingest Bundesbank Sanctions Compliance Guidance **[ESSENTIAL]**
- Download Deutsche Bundesbank guidance documents
- Chunk and embed with jurisdiction='DE'
- **Effort**: 0.5–1 day
- **Depends on**: Phase 1 ingestion pipeline
- **Acceptance**: "What does the Bundesbank expect for internal controls?" returns relevant German guidance.

**3.2.6** Ingest German Ministry FAQ on Russia Sanctions **[ESSENTIAL]**
- Download and process
- Tag with jurisdiction='DE', document_type='faq'
- **Effort**: 0.5 day
- **Depends on**: Phase 1 ingestion pipeline

### 3.3 Evaluation Foundation

**3.3.1** Build initial eval query set **[ESSENTIAL]**
- Create 50 test queries across all intent types (entity lookup, vessel, guidance, regulation, hybrid)
- Include expected intent classification for each
- Include expected source documents / entity matches where known
- Include at least 10 mixed-language or compound queries to test preprocessing
- **Effort**: 1 day (plus domain expert time)
- **Depends on**: Phase 2 agent (need working agent to evaluate)
- **[DOMAIN]**: Compliance expert provides or validates at least 30 of the 50 queries with expected answers.
- **Acceptance**: eval_queries.json with 50 entries, each having: query, expected_intent, expected_sources, and (for entity lookups) expected_entity_match.

**3.3.2** Build eval runner script **[ESSENTIAL]**
- Script that runs all eval queries through the agent
- Measures: intent classification accuracy, retrieval recall@5, retrieval recall@10, preprocessing quality (entity extraction accuracy, language detection)
- Outputs a summary report
- **Effort**: 1 day
- **Depends on**: 3.3.1
- **Acceptance**: Can run `python eval/run_eval.py` and get a classification accuracy score, retrieval metrics, and preprocessing metrics.

### Phase 3 Checkpoint

- [ ] All API endpoints working and documented in Swagger
- [ ] WebSocket streaming functional
- [ ] Conversation memory maintains context across follow-ups (preprocessing resolves implicit references)
- [ ] Data freshness endpoint reports accurate vintage per source
- [ ] OFAC General Licenses and FAQs ingested
- [ ] Reg. 833/2014 ingested with structure-aware chunking and article references
- [ ] EU FAQs, Bundesbank guidance, German Ministry FAQ ingested
- [ ] Eval harness running with 50-query test set
- [ ] Classification accuracy >85% on eval set
- [ ] Error handling and logging production-ready

---

## Phase 4 — Frontend (Weeks 10–11)

**Goal**: React frontend provides a usable chat interface with citations and entity cards. Build single-column first with inline citations, then promote to sidebar layout if time allows. Agent trace panel is a stretch goal.

### 4.1 Frontend Implementation

**4.1.1** Project setup **[ESSENTIAL]**
- Initialize React + TypeScript project (Vite)
- Set up Tailwind CSS (or similar) for styling
- Configure WebSocket client for streaming
- **Effort**: 0.5 day

**4.1.2** Chat panel component **[ESSENTIAL]**
- Message input with send button
- Message history display (user messages + assistant responses)
- Streaming response rendering (tokens appear as they arrive)
- Loading states and error display
- **Effort**: 2–3 days
- **Depends on**: 4.1.1, Phase 3 WebSocket endpoint
- **Acceptance**: Can type a query, see streaming response, view conversation history.

**4.1.3** Inline citation display **[ESSENTIAL]**
- Citations rendered below each assistant response in the agreed format from task 2.2.9
- Each citation shows: source document title, jurisdiction badge (US/EU/DE), relevant passage excerpt, article reference (for regulations), data vintage
- Click to expand full source context
- **Effort**: 1.5–2 days
- **Depends on**: 4.1.2
- **[DOMAIN]**: Show working citation display to compliance expert early — this is what makes the tool trustworthy.
- **Acceptance**: Citations appear below each response. Jurisdiction is clearly labeled. Article references are visible.

**4.1.4** Entity card component **[ESSENTIAL]**
- Structured display for entity lookup results
- Shows: primary name, aliases, entity type, source lists, programs, addresses, identifiers, DOB, nationality
- Visual indicator for multi-list entities (sanctioned under both OFAC and EU)
- Show known entity relationships (ownership, subsidiaries) with links
- **Effort**: 1.5–2 days
- **Depends on**: 4.1.2
- **Acceptance**: Entity lookups render as structured cards, not plain text. Relationships visible.

**4.1.5** Data freshness indicator **[ESSENTIAL]**
- Display data vintage for current response sources
- Warning indicator if any source data is older than expected refresh cadence
- Link to /api/data-status for full details
- **Effort**: 0.5 day
- **Depends on**: 4.1.2, Phase 3 data-status endpoint
- **Acceptance**: Every response shows "SDN data as of 2026-05-01" style indicator.

**4.1.6** Promote citations to sidebar layout **[RECOMMENDED]**
- Move citations from inline display to a dedicated right sidebar panel
- Split-view layout: chat (main) + citations (right sidebar)
- Responsive: panels stack on smaller screens
- **Effort**: 1–1.5 days
- **Depends on**: 4.1.3 (inline citations must work first)
- **Note**: Only attempt this if 4.1.2–4.1.5 are solid. A clean single-column layout with inline citations is better than a buggy split-view.
- **Acceptance**: Layout works on desktop. Panels are resizable or collapsible.

**4.1.7** Agent trace panel component **[RECOMMENDED]**
- Shows the agent's routing decision (classified intent, preprocessing output, which nodes executed)
- Displays timing for each step
- Collapsible/expandable (not all users need to see this)
- **Effort**: 1.5–2 days
- **Depends on**: 4.1.2
- **Note**: This is a portfolio differentiator — interviewers love seeing agent reasoning transparency. The preprocessing step (language detection, entity extraction, query decomposition) is especially interesting to demo. Prioritize it if time allows after 4.1.6.
- **Acceptance**: Can see "Preprocessing: DE→EN, entities: [Sovcomflot], sub-queries: 2 → Intent: hybrid → SQL + retrieval executed → synthesized → formatted (DE)" flow.

### Phase 4 Checkpoint

- [ ] Complete chat interface with streaming responses
- [ ] Inline citations showing sourced claims with jurisdiction labels
- [ ] Entity cards for structured entity results (including relationships and expanded fields)
- [ ] Data vintage visible in every response
- [ ] Layout is clean and professional enough for a demo
- [ ] Citation sidebar (if time allows)
- [ ] Agent trace panel (if time allows)

---

## Phase 5 — Validation & Tuning (Weeks 12–14)

**Goal**: Domain expert validates the system end-to-end. Retrieval quality is tuned based on real feedback. Remaining essential data sources are ingested. Fine-tuning evaluated if prompt engineering doesn't close quality gaps.

### 5.1 Domain Expert Validation

**5.1.1** Prepare validation session **[ESSENTIAL]**
- Create a structured validation protocol: 30–50 queries across all categories
- Include edge cases: dual-jurisdiction queries, vessel lookups, "what's authorized?" queries, mixed-language queries, compound questions
- Set up screen recording or structured feedback form
- **Effort**: 1 day prep
- **[DOMAIN]**: Full session with compliance expert (2–3 hours)

**5.1.2** Run validation session **[ESSENTIAL]**
- Domain expert runs queries through the full UI
- Record: correctness of response, citation accuracy, missing information, misleading statements, format preferences, language handling quality
- Note any query types that consistently fail
- **Effort**: 1 day (session + notes consolidation)
- **[DOMAIN]**: This is the most critical milestone in the project.

**5.1.3** Triage validation findings **[ESSENTIAL]**
- Categorize issues: retrieval quality, classification errors, preprocessing errors, synthesis errors, formatting errors, missing data, UI issues
- Prioritize fixes by impact
- **Effort**: 0.5 day
- **Depends on**: 5.1.2

### 5.2 Retrieval Tuning

**5.2.1** Tune retrieval based on validation findings **[ESSENTIAL]**
- Adjust chunk sizes if needed (especially for regulation documents)
- Tune BM25 vs. semantic weight in ensemble retriever
- Adjust top-k for retrieval
- Consider adding reranker if precision is lacking (start with cross-encoder/ms-marco-MiniLM-L-6-v2)
- **Effort**: 2–4 days (iterative, measurement-driven)
- **Depends on**: 5.1.3, 3.3.2 (eval harness)
- **Acceptance**: Retrieval recall@5 improves measurably on eval set after tuning.

**5.2.2** Tune classification prompt **[ESSENTIAL]**
- Refine classification prompt based on misclassified queries from validation
- Add edge case examples to prompt
- Re-run eval to confirm improvement
- **Effort**: 1–2 days
- **Depends on**: 5.1.3
- **Acceptance**: Classification accuracy >90% on eval set.

**5.2.3** Tune synthesis and formatting prompts **[ESSENTIAL]**
- Adjust response formatting based on domain expert feedback
- Improve citation specificity (e.g., include page numbers, article sub-paragraphs)
- Ensure authorization awareness: when identifying a blocked activity, proactively reference applicable General Licenses or EU derogations
- Tune language translation quality if German responses need improvement
- **Effort**: 1–2 days
- **Depends on**: 5.1.3
- **[DOMAIN]**: Iterate on response format with compliance expert.
- **Acceptance**: Domain expert confirms response format, citation quality, and language handling are acceptable.

### 5.3 Remaining Data Ingestion

**5.3.1** Ingest remaining enforcement PDFs **[ESSENTIAL]**
- Process full set of ~293 OFAC enforcement PDFs
- **Effort**: 1 day (pipeline already built, this is a batch run + quality check)
- **Depends on**: Phase 1 enforcement ingestion

**5.3.2** Ingest Reg. 269/2014 (EU individual designations) **[ESSENTIAL]**
- Process regulation text
- Tag with jurisdiction='EU', document_type='regulation'
- **Effort**: 1 day
- **Depends on**: Phase 1 ingestion pipeline, 3.2.3 structure-aware chunker

**5.3.3** Ingest EU derogation and authorization guidance **[ESSENTIAL]**
- Download Bundesbank derogation application guidance
- Tag appropriately
- **Effort**: 0.5 day
- **Depends on**: Phase 1 ingestion pipeline

**5.3.4** Ingest Bundesbank Financial Sanctions FAQ **[ESSENTIAL]**
- Download and process
- Tag with jurisdiction='DE', document_type='faq'
- **Effort**: 0.5 day

### 5.4 Fine-Tuning Evaluation (If Warranted)

Fine-tuning is NOT a default step. It is triggered only if prompt engineering + retrieval tuning (tasks 5.2.1–5.2.3) fail to close specific quality gaps identified during validation. Do not fine-tune preemptively.

**5.4.1** Assess fine-tuning need **[RECOMMENDED]**
- Review eval results after retrieval and prompt tuning. Identify remaining failure modes that prompt engineering cannot close.
- Likely candidates: intent classification consistency, citation format adherence, sanctions terminology parsing in preprocess_query
- If all metrics meet success criteria after prompt tuning, skip fine-tuning entirely
- **Effort**: 0.5 day (analysis only)
- **Depends on**: 5.2.1, 5.2.2, 5.2.3 (tuning must be completed first)
- **[DOMAIN]**: Review failure examples with compliance expert to confirm they're model failures, not retrieval failures
- **Acceptance**: Clear decision documented: fine-tune (with specific targets) or skip

**5.4.2** Build fine-tuning dataset **[RECOMMENDED — only if 5.4.1 says yes]**
- For intent routing: 200–500 example queries with correct classifications (draw from eval set + domain expert generated examples)
- For citation formatting: 100–300 examples of "retrieved context + question → properly formatted response" (generate with Mistral API as teacher, clean up with domain expert)
- For query preprocessing: 200–400 examples of raw analyst input → structured preprocessed output
- **Effort**: 2–3 days (including domain expert time for validation)
- **Depends on**: 5.4.1
- **[DOMAIN]**: Compliance expert validates training examples for domain accuracy

**5.4.3** Train and evaluate LoRA adapter **[RECOMMENDED — only if 5.4.2 complete]**
- Toolchain: Unsloth (explicit Devstral support, handles chat template correctly)
- Method: QLoRA on 24GB GPU. Starting hyperparameters: r=16, α=16, all-linear target modules, DoRA enabled
- Train separate adapters per task if targeting multiple weaknesses
- Evaluate on held-out test set. Compare before/after on specific failure modes.
- **Effort**: 1–2 days (training is hours, evaluation and iteration take the rest)
- **Depends on**: 5.4.2
- **Gotchas**: Do NOT fine-tune factual sanctions knowledge — that's what the RAG pipeline is for. The model should never "know" that an entity is sanctioned; it should retrieve that from PostgreSQL. Fine-tune only for format, routing, and language understanding.
- **Acceptance**: Measurable improvement on specific failure modes identified in 5.4.1. If no improvement, discard adapter and document findings.

### Phase 5 Checkpoint

- [ ] Domain expert has validated the system with structured feedback
- [ ] Validation findings triaged and critical issues fixed
- [ ] Classification accuracy >90%
- [ ] Retrieval quality measurably improved after tuning
- [ ] All essential data sources ingested (19 of 25)
- [ ] Authorization-aware responses (mentions GLs and derogations when relevant)
- [ ] Fine-tuning decision documented (trained adapter with measured improvement, or decision to skip with rationale)

---

## Phase 6 — Deployment & Polish (Weeks 15–16)

**Goal**: Deploy to AWS. Self-hosted LLM demo working. Automated daily ingestion. Portfolio documentation complete.

### 6.1 AWS Deployment

**6.1.1** Terraform infrastructure setup **[ESSENTIAL]**
- VPC with public + private subnets
- RDS PostgreSQL (pgvector) in private subnet, KMS encrypted
- EC2 instance(s) for backend + LLM inference behind ALB
- S3 buckets (data lake + frontend static hosting)
- CloudFront distribution for frontend
- Security groups: ALB → EC2 → RDS (least privilege)
- **Effort**: 2–3 days
- **Acceptance**: Infrastructure provisioned. Can SSH to EC2 and connect to RDS from within VPC.

**6.1.2** Deploy backend to EC2 **[ESSENTIAL]**
- Dockerized FastAPI backend running on EC2
- ALB with TLS termination (ACM certificate)
- Environment variables via AWS Secrets Manager or SSM Parameter Store
- **Effort**: 1–1.5 days
- **Depends on**: 6.1.1
- **Acceptance**: API reachable via HTTPS through ALB. Health check passing.

**6.1.3** Deploy frontend to S3 + CloudFront **[ESSENTIAL]**
- Build React app, deploy static files to S3
- CloudFront distribution with HTTPS
- API calls route to ALB
- **Effort**: 0.5–1 day
- **Depends on**: 6.1.1
- **Acceptance**: Frontend loads via CloudFront URL. Chat works end-to-end.

**6.1.4** Database migration on RDS **[ESSENTIAL]**
- Run alembic migrations on RDS
- Seed data: run full ingestion pipeline against RDS
- Verify data integrity
- **Effort**: 1 day
- **Depends on**: 6.1.1
- **Acceptance**: All data migrated. Queries return same results as local.

### 6.2 Self-Hosted LLM

**6.2.1** Ollama + Ministral 14B setup **[ESSENTIAL]**
- Install Ollama on EC2 (g5.xlarge with A10G GPU)
- Pull and configure Ministral 14B
- Point backend to local Ollama endpoint via env vars
- If fine-tuned LoRA adapter exists (from 5.4.3), deploy merged model via Ollama custom Modelfile or switch to vLLM with adapter support
- **Effort**: 0.5–1 day (add 0.5 day if deploying fine-tuned adapter)
- **Depends on**: 6.1.2
- **Acceptance**: Agent works end-to-end with local Ministral 14B (with or without adapter). No external API calls.

**6.2.2** Self-hosted LLM quality evaluation **[ESSENTIAL]**
- Run full eval set against Ministral 14B (and adapter variant if applicable)
- Compare quality against Mistral cloud API baseline
- Document quality gaps (expected: some degradation on complex regulation queries)
- Adjust synthesis prompt if needed for smaller model
- **Effort**: 1–2 days
- **Depends on**: 6.2.1, eval harness
- **[DOMAIN]**: If possible, quick check with compliance expert on Ministral 14B output quality.
- **Acceptance**: Quality assessment documented. Key trade-offs noted. Agent is usable (even if not perfect) with 14B model.

### 6.3 Automated Ingestion

**6.3.1** Automated daily sanctions list refresh **[ESSENTIAL]**
- Cron job (or simple scheduler) on EC2 that runs incremental ingestion for OFAC SDN + EU Consolidated List daily
- Sends alert (email or log) on ingestion failure
- Sends alert if source data hasn't changed in >3 days (possible fetch failure)
- **Effort**: 1 day
- **Depends on**: 6.1.2, Phase 1 incremental logic
- **Acceptance**: SDN + EU list data updates automatically. Ingestion log reflects daily runs.

### 6.4 Portfolio Documentation

**6.4.1** Architecture writeup **[ESSENTIAL]**
- Detailed README.md covering: problem statement, architecture diagram, tech stack decisions, agent design (including preprocessing and formatting pipeline), retrieval strategy, security architecture
- Include architecture diagram (draw.io or similar)
- Highlight key engineering decisions and trade-offs
- If fine-tuning was attempted, document the methodology, results, and decision
- **Effort**: 1–1.5 days

**6.4.2** Demo preparation **[ESSENTIAL]**
- Prepare 5–10 demo queries that showcase different capabilities (entity lookup, vessel search, regulation interpretation, dual-jurisdiction, enforcement precedent, mixed-language query, compound question)
- Include at least one German-language query to demo the preprocessing pipeline
- Record short demo video or prepare live demo script
- **Effort**: 0.5–1 day
- **[DOMAIN]**: Compliance expert helps select the most impressive demo queries.

**6.4.3** Cost analysis and scaling documentation **[RECOMMENDED]**
- Document actual costs (dev, PoC, projected production)
- Write up the scaling path: what changes going from PoC to bank production
- **Effort**: 0.5 day

### Phase 6 Checkpoint

- [ ] Full application deployed on AWS and accessible via HTTPS
- [ ] Self-hosted Ministral 14B working (with adapter if applicable) with quality assessment documented
- [ ] Automated daily ingestion running for sanctions lists
- [ ] Privacy architecture demonstrable: zero external API calls in self-hosted mode
- [ ] Portfolio README complete with architecture diagram
- [ ] Demo script prepared with showcase queries (including mixed-language demo)
- [ ] Project ready for portfolio presentation and interviews

---

## Summary: Task Count by Priority

| Priority | Count | Notes |
|---|---|---|
| **ESSENTIAL** | ~52 tasks | Must complete for a functional, demo-ready PoC |
| **RECOMMENDED** | ~7 tasks | Add quality, cut if time pressure (includes citation sidebar, agent trace panel, fine-tuning) |
| **DOMAIN** | ~13 touchpoints require expert input | Schedule these early — domain expert time is the bottleneck |

## Risk Checkpoints

- **End of Week 3**: If ingestion pipeline isn't working with relationships and expanded fields, the whole project is blocked. This is the earliest point where things can go wrong.
- **End of Week 6**: If the agent can't classify and route correctly, you need to simplify (e.g., drop hybrid routing, do explicit UI-driven routing instead). If preprocessing is struggling with German queries, simplify to English-only for MVP and add language handling as a tuning task in Phase 5.
- **End of Week 9**: If Reg. 833/2014 structure-aware chunking is blocked, fall back to paragraph-level chunking with heuristic article tagging. Don't let it delay the frontend.
- **End of Week 11**: If the frontend isn't functional, cut the citation sidebar and agent trace panel. The core single-column chat with inline citations must work.
- **End of Week 14**: If Ministral 14B quality is unacceptable, fall back to Mistral API for the demo and document the self-hosted architecture as "ready for deployment with larger model." If fine-tuning didn't help, document findings — that's still a strong portfolio talking point.

## Domain Expert Scheduling

Book these sessions early — they require advance preparation and the compliance expert has limited availability:

1. **Week 3**: Entity data review — show the output for 3–4 sample entities (e.g., Sovcomflot, a sanctioned bank, a vessel, an individual). "Here's what we captured — name, aliases, DOB, nationality, identifiers, programs, legal basis, linked vessels, ownership relationships. Is anything missing that you'd expect to see in an investigation?" Not a database walkthrough — show analyst-facing output.
2. **Week 4**: Provide 50+ example queries for classification prompt and eval set. Include messy real-world examples: mixed-language, abbreviations, compound questions, shorthand. These feed the preprocessing prompt.
3. **Weeks 4–5 (async)**: Citation format review — send 3 mockup formats via email/message. "Which format would you want to see when investigating an alert?" Quick turnaround, does not require a meeting.
4. **Week 8**: Review response structure on sample outputs with real data. Confirm citation format works in practice. Test German-language query handling. Flag any document types where retrieval quality is weak.
5. **Weeks 12–13**: Full validation session (2–3 hours). This is the most important session. Bring the complete UI with all essential data sources loaded.
6. **Week 16**: Help select demo queries and quick review of final outputs. Include at least one mixed-language query for the demo.
