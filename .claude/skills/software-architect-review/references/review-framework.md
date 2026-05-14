# Review Framework — Core Principles & Red Flags

## The Five Pillars (in priority order)

### 1. Simplicity (YAGNI + KISS)
*You Aren't Gonna Need It. Keep It Simple, Stupid.*

**What to check:**
- Is every file, class, and function solving a problem that exists *right now*?
- Can the same result be achieved with fewer moving parts?
- Is there any speculative generality — code written "just in case" we need it?

**How to measure it:**
Ask: *"If I deleted this, would anything currently break?"* If no → flag it.

**Acceptable complexity threshold for MVP:**
A new developer should be able to trace a full request (HTTP in → agent pipeline → DB query/retrieval → response out)
in under 30 minutes using only the code and the project constitution (`CLAUDE.md`).

---

### 2. Single Responsibility
*Each module, class, and function does exactly one thing.*

**What to check:**
- Does any service/node have more than one reason to change?
- Does any function do more than one logical operation?
- Are there "God objects" — classes that know too much about the system?

**FastAPI + LangGraph-specific signals:**
- A router file that contains business logic → violation.
- An agent node that handles both SQL lookup AND retrieval → violation (separate nodes per the constitution).
- A repository that touches more than one domain table → violation.
- A Pydantic schema used for both input validation AND database serialization → violation. Use separate `Request`/`Response` schemas.

---

### 3. Extensibility (Open/Closed Principle)
*Open for extension. Closed for modification.*

**The key question:** When feature X is added, how many existing files need to change?

**Good sign:** New features add new files. Existing files are untouched.
**Bad sign:** New features require editing core agent logic, switching on a new type.

**For Sanctions Screening Assistant specifically — watch for:**
- Hardcoded intent types inside `classify_query` routing logic.
  New intents should be added via configuration/registration, not `if/elif` chains.
- Hardcoded source types (`'ofac_sdn'`, `'eu_consolidated'`) inside retrieval logic.
  Source types should come from metadata, not service-layer conditionals.
- Hardcoded jurisdiction codes (`'US'`, `'EU'`, `'DE'`) inside business logic.
  These should be passed as parameters, not baked into conditionals.
- Prompt templates that assume a single query type.
  They should accept intent/context as parameters.

---

### 4. Maintainability
*Code is read 10x more than it is written.*

**What to check:**
- Are function and variable names self-documenting?
- Is there any "magic" — unexplained constants, unclear conditionals?
- Are errors handled explicitly, or silently swallowed?
- Is there a clear separation between what the system *does* and *how it does it*?

**Key maintainability rules for this project:**
- All LLM prompt templates live in `app/agent/prompts/`. Nowhere else.
- All environment config is loaded via `config.py`. No `os.environ.get()` scattered in services.
- All DB session management uses the dependency injection from `dependencies.py`. No manual session handling.
- All logging via `structlog`. No `print()` statements.
- LLM calls go through `app/llm/client.py`. No direct provider SDK usage elsewhere.

---

### 5. Modularity
*Modules are independently understandable, testable, and replaceable.*

**What to check:**
- Can the LLM client be replaced with a different provider by changing `app/llm/client.py` + env vars?
- Can the embedding model be swapped by changing `app/retrieval/embeddings.py` only?
- Can a new data source be ingested by adding a parser in `ingestion/pipeline/sources/` only?
- Do agent nodes import from each other? (They should receive input from the graph state, not call each other directly.)

**Dependency direction (must always flow this way):**
```
routers → agent graph → nodes → repositories/retrieval
routers → agent graph → nodes → llm client
repositories → models/schemas
NEVER: nodes → routers
NEVER: models → services/nodes
NEVER: nodes → other nodes directly (use graph state)
```

---

## Red Flags Checklist

Run through this for every plan review. Each "YES" is a flag to raise.

### Architecture Red Flags
- [ ] An agent node handles more than one concern (e.g., SQL + retrieval in one node)
- [ ] Business logic exists in a router function
- [ ] A model has methods that call services or external APIs
- [ ] Agent nodes import and call other nodes directly (bypassing graph state)
- [ ] Hardcoded LLM model names or provider-specific features in agent nodes
- [ ] The plan introduces a new layer of abstraction without 2+ concrete use cases
- [ ] Responses can be generated without source citations or data vintage

### FastAPI-Specific Red Flags
- [ ] Pydantic schemas used as SQLAlchemy models (or vice versa)
- [ ] DB session created manually outside of dependency injection
- [ ] `async def` route calling a blocking (sync) function without `run_in_executor`
- [ ] Response model missing — endpoint returns raw dict or SQLAlchemy object
- [ ] No error handling — service exceptions propagate unhandled to the client
- [ ] `print()` statements instead of `structlog` logging

### Schema Red Flags
- [ ] Missing `data_vintage` on any table that stores external data
- [ ] Missing `last_updated` on any table that gets mutated
- [ ] JSONB used for data that needs to be queried/filtered (should be a column)
- [ ] FK without cascade rule defined (what happens when parent is deleted?)
- [ ] New table added without checking if existing FK relationships remain stable
- [ ] `source` or `jurisdiction` not tracked on data that comes from external sources

### Domain-Specific Red Flags
- [ ] An API response path that can produce output without citation metadata
- [ ] Data vintage not propagated through the full pipeline (ingestion → storage → response)
- [ ] Entity lookup that doesn't account for aliases (entity_aliases table)
- [ ] Vessel lookup that doesn't use IMO number as primary identifier
- [ ] 50% Rule chain traversal that doesn't check transitive ownership
- [ ] Retrieval results that don't include jurisdiction metadata

### Complexity Red Flags
- [ ] A new external service introduced before measuring a bottleneck
- [ ] A class hierarchy (inheritance) introduced without 2+ concrete subclasses
- [ ] More than 3 levels of function call nesting to complete a single operation
- [ ] A "util" or "helper" file that accumulates unrelated functions

---

## Verdict Decision Matrix

| Issues Found                              | Verdict              |
|------------------------------------------|----------------------|
| No red flags, minor suggestions only     | APPROVED             |
| 1-2 warnings, no critical issues        | APPROVED WITH NOTES  |
| 1+ critical issues (fixable)            | NEEDS REVISION       |
| Fundamental design flaw / wrong approach | REJECTED             |
