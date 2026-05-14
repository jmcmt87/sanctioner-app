# Extensibility Patterns for Growing Projects

## The Core Question Before Every Feature

Before approving any new feature design, ask:
> "When the *next* feature after this one is added, how much of *this* code needs to change?"

If the answer is "a lot" → the current design is not extensible enough.
If the answer is "almost nothing, just add new files" → the design is good.

---

## Pattern 1: Registry Pattern for Agent Intent Routing

**The problem:** The `classify_query` node routes queries to different paths.
A naive implementation puts conditionals everywhere:

```python
# BAD — this will rot
async def classify_query(state):
    if intent == 'entity_lookup':
        return "execute_sql"
    elif intent == 'vessel_lookup':
        return "execute_sql"
    elif intent == 'guidance_search':
        return "retrieve_docs"
    elif intent == 'regulation_check':
        return "retrieve_docs"
    elif intent == 'hybrid':
        return "both"
```

Every new intent requires modifying the routing logic. This is fragile.

**The extensible approach — use configuration-driven routing:**

```python
# app/agent/state.py or config
INTENT_ROUTING = {
    "entity_lookup": "execute_sql",
    "vessel_lookup": "execute_sql",
    "guidance_search": "retrieve_docs",
    "regulation_check": "retrieve_docs",
    "hybrid": "both",
    # Future: "enforcement_search": "retrieve_docs",
    # Future: "ownership_chain": "execute_sql",
}

# In classify_query node
async def classify_query(state):
    intent = await determine_intent(state)
    route = INTENT_ROUTING.get(intent, "both")  # default to hybrid
    return route
```

**Result:** Adding a new intent = adding one line to the dict + a new node if needed.
Zero changes to routing logic.

---

## Pattern 2: Source-Agnostic Ingestion

**The problem:** Hardcoded source handling in the ingestion pipeline.

```python
# BAD
if source == 'ofac_sdn':
    parse_ofac_sdn(data)
elif source == 'eu_consolidated':
    parse_eu_xml(data)
```

**The correct approach:** Each source has its own parser module in `ingestion/pipeline/sources/`.
The pipeline runner discovers and invokes them:

```python
# GOOD — each source is a self-contained module with a standard entry point
# ingestion/pipeline/sources/ofac_sdn.py
async def ingest_ofac_sdn(session, s3_client, config) -> IngestionResult:
    ...

# ingestion/pipeline/runner.py — registry maps source names to functions
REGISTERED_SOURCES = {
    "ofac_sdn": ingest_ofac_sdn,
    "eu_consolidated": ingest_eu_sanctions,
    # Future: just add a new entry + a new file in sources/
}

async def run_ingestion(sources: list[str] | None = None):
    targets = sources or REGISTERED_SOURCES.keys()
    for source_name in targets:
        handler = REGISTERED_SOURCES[source_name]
        result = await handler(session, s3_client, config)
        log_ingestion_result(result)
```

Adding a new sanctions list = creating a new file in `sources/` and registering it.

**Note:** When the project has 6+ sources and parsers need shared setup/teardown
logic, refactor to a protocol or base class. Not before.

---

## Pattern 3: The "Seam" — Where New Features Plug In

A well-designed system has clear "seams" — extension points where new features attach
without modifying existing code. For the Sanctions Screening Assistant, the seams are:

| Future Feature             | Seam (where it plugs in)                           | What doesn't change              |
|----------------------------|---------------------------------------------------|----------------------------------|
| New sanctions list source  | New parser in `ingestion/pipeline/sources/`        | Runner, chunking, embedding      |
| New agent intent           | New entry in `INTENT_ROUTING` + optional new node  | Other nodes, graph structure      |
| New retrieval strategy     | New module in `app/retrieval/`                     | Agent nodes, API layer           |
| New jurisdiction (e.g. UK) | New `jurisdiction` value in metadata               | All services, schema, pipeline   |
| LLM provider swap          | Three env vars (`SSA_LLM_*`)                       | All code — zero changes          |
| Embedding model swap       | Change model name in config                        | Retrieval logic, ingestion flow  |
| Reranker addition          | New module `app/retrieval/reranker.py`              | BM25, vector_store, ensemble     |
| New document type          | New `document_type` value + optional chunker        | Retrieval, agent, API            |

When reviewing a new feature plan, check: *does it plug into an existing seam,
or does it require cutting a new one?* Cutting new seams is fine. Destroying
existing seams is not.

---

## Pattern 4: Configuration Over Conditionals

When behavior needs to vary (by jurisdiction, by source type, by confidence threshold),
prefer configuration tables/dicts over `if/elif` chains.

```python
# BAD — grows forever, lives in service logic
def get_refresh_cadence(source: str) -> timedelta:
    if source == 'ofac_sdn':
        return timedelta(hours=24)
    elif source == 'eu_consolidated':
        return timedelta(hours=24)
    elif source == 'ofac_general_licenses':
        return timedelta(days=7)
    ...

# GOOD — declarative, lives in config
REFRESH_CADENCES = {
    "ofac_sdn": timedelta(hours=24),
    "ofac_nonsdn": timedelta(hours=24),
    "ofac_vessels": timedelta(hours=24),
    "eu_consolidated": timedelta(hours=24),
    "ofac_general_licenses": timedelta(days=7),
    "eu_regulations": timedelta(days=7),
    "eu_faqs": timedelta(days=30),
    "ofac_enforcement": timedelta(days=30),
    "de_guidance": timedelta(days=90),
}
```

---

## Anti-Patterns to Flag

### The Premature Interface
Creating abstract base classes or protocols before there are 2+ concrete implementations.

```python
# TOO EARLY — there's only one retrieval strategy right now
class AbstractRetriever(ABC):
    @abstractmethod
    async def retrieve(self): ...

class SemanticRetriever(AbstractRetriever):
    ...
```

**When to use it:** When the ensemble retriever is being built (BM25 + semantic).
Not before.

### The Mega-Node
A single agent node that handles too many concerns because "it's all related."

```python
# BAD — one node doing too much
async def process_query(state):
    # normalizes language
    # extracts entities
    # classifies intent
    # runs SQL
    # retrieves docs
    # synthesizes response
    ...
```

**Rule:** Each node in the LangGraph pipeline handles exactly one concern.
This is defined in the constitution: preprocess, classify, sql_lookup, retrieve,
synthesize, format_response.

### The Leaky Schema
A Pydantic response schema that exposes internal DB fields the client doesn't need.

```python
# BAD — client now depends on internal DB fields
class EntityResponse(BaseModel):
    id: UUID
    source_id: str           # internal identifier
    raw_record: dict          # full OFAC/EU raw data
    embedding: list[float]    # definitely not the client's business
    ...

# GOOD — only what the client actually needs
class EntitySearchResult(BaseModel):
    entity_id: UUID
    primary_name: str
    source: str
    programs: list[str]
    aliases: list[str]
    data_vintage: datetime
```
