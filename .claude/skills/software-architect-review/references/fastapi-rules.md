# FastAPI-Specific Rules & Best Practices

## Layer Architecture (Non-Negotiable)

```
HTTP Request / WebSocket
    ↓
[Router]          — Validates input shape, calls agent/service, returns response.
                    No business logic. No DB access. No LLM calls.
    ↓
[Agent Graph]     — LangGraph state machine. Orchestrates nodes.
    ↓
[Nodes]           — Each node does one thing: preprocess, classify, sql_lookup,
                    retrieve, synthesize, or format. Business logic lives here.
    ↓
[Repositories]    — Data access layer. One per domain (entities, documents, ingestion).
    ↓
[Models/Schemas]  — Data shapes only. No logic.
    ↓
[Database]        — PostgreSQL + pgvector. Accessed only via repository layer.
```

**The litmus test:** If you copy an agent node into a CLI script, it should work
without importing anything from FastAPI. If it can't, the layer boundary is broken.

---

## Dependency Injection Patterns

### Database Session (Correct)
```python
# session.py
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

# In dependencies.py (correct — centralized DI)
async def get_entity_repository(
    session: AsyncSession = Depends(get_async_session),
) -> EntityRepository:
    return EntityRepository(session)

# In a router (correct)
@router.get("/api/entity-search")
async def entity_search(
    query: str,
    repo: EntityRepository = Depends(get_entity_repository),
):
    return await repo.search(query)
```

### Config (Correct)
```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ssa_llm_base_url: str
    ssa_llm_model_name: str
    ssa_llm_api_key: str = ""
    ssa_database_url: str
    ssa_embedding_model: str = "BAAI/bge-m3"

    model_config = SettingsConfigDict(env_prefix="SSA_")

settings = Settings()

# Usage — import settings, never os.environ.get() directly in services
from app.config import settings
```

---

## Pydantic Schema Rules

### Use Separate Request/Response Schemas
```python
# WRONG — one schema for everything
class Entity(BaseModel):
    id: UUID
    source: str
    source_id: str
    primary_name: str
    raw_record: dict
    ...

# CORRECT — separate schemas per use case
class EntitySearchRequest(BaseModel):
    query: str
    jurisdiction: str | None = None
    entity_type: str | None = None

class EntitySearchResponse(BaseModel):
    entity_id: UUID
    primary_name: str
    source: str
    programs: list[str]
    legal_basis: list[str]
    aliases: list[str]
    data_vintage: datetime

class QueryRequest(BaseModel):
    query: str
    conversation_id: UUID | None = None

class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    data_vintage: dict[str, datetime]
    jurisdictions_consulted: list[str]
```

### Always Define Response Models on Routes
```python
# WRONG
@router.post("/api/query")
async def query(request: QueryRequest, ...):
    ...  # returns raw dict

# CORRECT
@router.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest, ...):
    ...
```

---

## Async Rules

### Blocking Calls in Async Context
```python
# WRONG — blocks the event loop
@router.get("/something")
async def get_something():
    result = requests.get("https://api.example.com")  # sync HTTP in async route

# CORRECT — use async libraries
@router.get("/something")
async def get_something():
    async with httpx.AsyncClient() as client:
        result = await client.get("https://api.example.com")
```

### WebSocket Streaming (for /api/stream)
```python
# CORRECT — streaming agent responses via WebSocket
@router.websocket("/api/stream")
async def stream_query(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_json()
    async for chunk in agent.astream(data["query"]):
        await websocket.send_json(chunk)
    await websocket.close()
```

---

## Error Handling Pattern

### Service/Node Layer — Raise Domain Exceptions
```python
# app/exceptions.py
class EntityNotFound(Exception):
    pass

class DataVintageStale(Exception):
    pass

class LLMParseError(Exception):
    pass

class RetrievalError(Exception):
    pass

# In a repository
async def get_entity(self, entity_id: UUID) -> SanctionedEntity:
    entity = await self.session.get(SanctionedEntity, entity_id)
    if not entity:
        raise EntityNotFound(f"Entity {entity_id} not found")
    return entity
```

### Router Layer — Catch and Convert to HTTP Exceptions
```python
# In router
@router.get("/api/entity-search")
async def entity_search(query: str, repo: EntityRepository = Depends(...)):
    try:
        return await repo.search(query)
    except EntityNotFound:
        raise HTTPException(status_code=404, detail="Entity not found")
```

---

## LLM Client Abstraction Pattern

The LLM client must be a pure wrapper around whichever provider is configured.
It should not contain business logic — only the mechanics of calling the API
and parsing the response.

```python
# CORRECT structure — app/llm/client.py
class LLMClient:
    def __init__(self, settings: Settings):
        self.base_url = settings.ssa_llm_base_url
        self.model = settings.ssa_llm_model_name
        self.api_key = settings.ssa_llm_api_key

    async def complete(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        # Uses OpenAI-compatible API (works with Mistral, Ollama, vLLM)
        ...
```

**Key rule:** The LLM client never builds prompts. Agent nodes build prompts using
templates from `app/agent/prompts/`, then pass them to the LLM client. This means
you can test prompt construction independently of API calls.

---

## Alembic Migration Rules

1. **Never edit a migration file after it has been applied** — even in dev.
   Create a new migration instead.
2. **Always run `alembic upgrade head` in CI** before tests, not just locally.
3. **Review autogenerated migrations** — Alembic sometimes misses column renames
   (it sees a DROP + ADD instead of ALTER). Always check the generated SQL.
4. **One migration per logical change** — don't bundle unrelated schema changes.
5. **pgvector operations** — ensure migrations handle `CREATE EXTENSION vector` and
   HNSW index creation correctly.
