# Sanctions Screening Assistant — Testing Priorities & LLM Mocking

## What to Test First (Priority Order)

Start here. Do not skip ahead.

### Priority 1 — Agent Node Logic (`tests/test_agent/`)
These are the core of the pipeline. Mock the LLM client entirely.
They're also the most fragile part — a broken node silently produces
wrong routing, missing citations, or stale data without any error.

**Must cover:**
- `preprocess_query` — entity extraction, language detection, query decomposition
- `classify_query` — intent routing produces correct intent for each query type, fallback to hybrid on low confidence
- `synthesize` — citation metadata is included in every response, jurisdiction labeling is correct
- `format_response` — data vintage disclaimer is added, citation format is enforced

### Priority 2 — Repository Layer (`tests/test_api/`)
The data access layer. Use real PostgreSQL via testcontainers.

**Must cover:**
- Entity search by name (exact + fuzzy via pg_trgm)
- Entity search via aliases (entity_aliases table)
- Vessel lookup by IMO number
- Vessel lookup by name
- Relationship traversal (entity_relationships) for 50% Rule chains
- Every search result includes `data_vintage` metadata
- Jurisdiction filtering works correctly

### Priority 3 — Retrieval Pipeline (`tests/test_retrieval/`)
The RAG components. Test with real pgvector where possible.

**Must cover:**
- BM25 full-text search returns relevant chunks
- Semantic search via pgvector returns relevant chunks
- Ensemble retriever merges BM25 + semantic via RRF correctly
- Metadata filtering (jurisdiction, document_type, date range)
- Results include source metadata (source_document, article_reference, data_vintage)

### Priority 4 — Router Contracts (`tests/test_api/`)
HTTP contracts only. Status codes and response shapes.

**Must cover:**
- `POST /api/query` → 200 with valid query, response includes citations + data_vintage
- `POST /api/query` → 422 with empty/invalid query
- `GET /api/entity-search` → 200 with results
- `GET /api/entity-search` → 200 with empty results (valid but no matches)
- `WebSocket /api/stream` → streams chunks with correct format

### Priority 5 — Ingestion Parsers (`ingestion/tests/`)
**Must cover:**
- OFAC SDN CSV parsing produces correct SanctionedEntity records
- EU Consolidated List XML parsing produces correct records
- Data vintage is set on every parsed record
- Malformed input is handled gracefully (logged, not crashed)

---

## Mocking the LLM Client — The Right Way

**Never call the real LLM API in tests.** It costs money, it's slow, and
it's non-deterministic. Always mock `LLMClient` at the node/service layer.

### Standard LLM Mock Fixture

```python
# Add this to conftest.py or the specific test file

from unittest.mock import AsyncMock
import json


@pytest.fixture
def mock_llm_client():
    """Mock LLM client so tests never hit Mistral/Ollama/vLLM."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_llm_classify(mock_llm_client):
    """LLM returns a classification response."""
    mock_llm_client.complete.return_value = json.dumps({
        "intent": "entity_lookup",
        "confidence": 0.95,
        "reasoning": "Query asks about a specific entity by name",
    })
    return mock_llm_client


@pytest.fixture
def mock_llm_preprocess(mock_llm_client):
    """LLM returns a preprocessed query response."""
    mock_llm_client.complete.return_value = json.dumps({
        "original_query": "Is Sberbank sanctioned?",
        "normalized_query": "Is Sberbank on the sanctions list?",
        "entities": ["Sberbank"],
        "regulations_referenced": [],
        "sub_queries": [],
        "source_language": "en",
    })
    return mock_llm_client


@pytest.fixture
def mock_llm_synthesize(mock_llm_client):
    """LLM returns a synthesized response with citations."""
    mock_llm_client.complete.return_value = json.dumps({
        "answer": "Sberbank (Public Joint Stock Company Sberbank of Russia) is listed on the OFAC SDN list under program RUSSIA-EO14024 [1]. Under EU sanctions, Sberbank is listed in Regulation 269/2014 [2].",
        "citations": [
            {"index": 1, "source": "OFAC SDN List", "reference": "Entry 12345", "jurisdiction": "US"},
            {"index": 2, "source": "EU Reg. 269/2014", "reference": "Annex I", "jurisdiction": "EU"},
        ],
        "jurisdictions": ["US", "EU"],
    })
    return mock_llm_client


@pytest.fixture
def mock_llm_malformed(mock_llm_client):
    """LLM returns unparseable output — tests error handling."""
    mock_llm_client.complete.side_effect = ValueError(
        "Failed to parse LLM response as JSON"
    )
    return mock_llm_client
```

### Testing Error Handling for Malformed LLM Responses

This is critical. LLMs occasionally return malformed JSON. Your nodes must handle it.

```python
async def test_classify_handles_llm_parse_error(mock_llm_malformed):
    """If the LLM returns malformed JSON, classify_query raises a handled error."""
    from app.exceptions import LLMParseError

    state = AgentState(normalized_query="Is Sberbank sanctioned?")

    with pytest.raises(LLMParseError):
        await classify_query(state, llm_client=mock_llm_malformed)
```

---

## Data Vintage Tests

Data vintage propagation is a critical constraint. Test it explicitly:

```python
async def test_response_includes_data_vintage(client, mock_agent):
    """Every API response must include data_vintage metadata."""
    response = await client.post("/api/query", json={"query": "Is Sberbank sanctioned?"})
    data = response.json()
    assert "data_vintage" in data
    assert isinstance(data["data_vintage"], dict)
    assert len(data["data_vintage"]) > 0


async def test_entity_search_includes_vintage(client, test_entity):
    """Entity search results must include data_vintage per entity."""
    response = await client.get("/api/entity-search", params={"query": "Test Bank"})
    data = response.json()
    for entity in data:
        assert "data_vintage" in entity
```

---

## Running Only Specific Test Layers (Fast Feedback Loop)

```bash
# Just agent node tests (needs LLM mock only, fast)
cd backend && uv run pytest tests/test_agent/ -v

# Repository tests (needs Docker for PostgreSQL)
uv run pytest tests/test_api/ -v

# Retrieval tests (needs Docker + pgvector)
uv run pytest tests/test_retrieval/ -v

# Full suite with coverage
uv run pytest --cov=app --cov-report=term-missing

# Skip slow integration tests during development
uv run pytest -m "not integration" -v
```

Mark slow tests with `@pytest.mark.integration` so they can be skipped locally
but always run in CI.
