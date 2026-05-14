# Test Patterns by Layer

## Layer 1: Agent Node Tests

Agent nodes contain the core pipeline logic. These are the most important tests.
Test nodes directly via their function signatures — do NOT go through the HTTP layer.

### Pattern: classify_query Node

```python
# tests/test_agent/test_classify.py
from unittest.mock import AsyncMock
import pytest

from app.agent.nodes.classify import classify_query
from app.agent.state import AgentState


@pytest.fixture
def mock_llm_client():
    """Mock LLM client so tests never hit the real API."""
    mock = AsyncMock()
    mock.complete.return_value = '{"intent": "entity_lookup", "confidence": 0.95}'
    return mock


async def test_classify_entity_lookup(mock_llm_client):
    """classify_query should route entity name queries to entity_lookup."""
    state = AgentState(
        normalized_query="Is Sberbank on the SDN list?",
        entities=["Sberbank"],
    )
    result = await classify_query(state, llm_client=mock_llm_client)
    assert result.intent == "entity_lookup"
    assert result.confidence >= 0.8


async def test_classify_falls_back_to_hybrid_on_low_confidence(mock_llm_client):
    """classify_query should fall back to hybrid when confidence is low."""
    mock_llm_client.complete.return_value = '{"intent": "entity_lookup", "confidence": 0.3}'
    state = AgentState(normalized_query="Tell me about Russia sanctions")
    result = await classify_query(state, llm_client=mock_llm_client)
    assert result.intent == "hybrid"
```

### Pattern: preprocess_query Node

```python
# tests/test_agent/test_preprocess.py
async def test_preprocess_extracts_entity_names(mock_llm_client):
    """preprocess should extract entity names from natural language queries."""
    mock_llm_client.complete.return_value = json.dumps({
        "normalized_query": "Is Sberbank on the sanctions list?",
        "entities": ["Sberbank"],
        "regulations_referenced": [],
        "sub_queries": [],
        "source_language": "en",
    })
    state = AgentState(original_query="Is Sberbank on the sanctions list?")
    result = await preprocess_query(state, llm_client=mock_llm_client)
    assert "Sberbank" in result.entities


async def test_preprocess_handles_german_input(mock_llm_client):
    """preprocess should detect German input and normalize to English."""
    mock_llm_client.complete.return_value = json.dumps({
        "normalized_query": "Is Sberbank sanctioned under EU law?",
        "entities": ["Sberbank"],
        "regulations_referenced": ["Reg. 269/2014"],
        "sub_queries": [],
        "source_language": "de",
    })
    state = AgentState(original_query="Ist Sberbank unter EU-Recht sanktioniert?")
    result = await preprocess_query(state, llm_client=mock_llm_client)
    assert result.source_language == "de"
    assert "Sberbank" in result.entities
```

---

## Layer 2: Repository Tests

Repository tests verify data access logic against a real PostgreSQL instance.
Use the `db_session` fixture from conftest which rolls back after each test.

```python
# tests/test_api/test_entity_repository.py
import pytest
import uuid
from datetime import datetime, timezone

from app.db.repositories.entity_repository import EntityRepository
from app.db.models import SanctionedEntity, EntityAlias


async def test_search_by_name_finds_exact_match(db_session):
    """Entity search should find exact name matches."""
    entity = SanctionedEntity(
        id=uuid.uuid4(),
        source="ofac_sdn",
        source_id="99999",
        entity_type="entity",
        primary_name="Gazprombank",
        programs=["RUSSIA-EO14024"],
        last_updated=datetime.now(timezone.utc),
        data_vintage=datetime.now(timezone.utc),
    )
    db_session.add(entity)
    await db_session.flush()

    repo = EntityRepository(db_session)
    results = await repo.search("Gazprombank")
    assert len(results) >= 1
    assert results[0].primary_name == "Gazprombank"


async def test_search_by_alias_finds_entity(db_session):
    """Entity search should find entities via their aliases."""
    entity = SanctionedEntity(
        id=uuid.uuid4(),
        source="ofac_sdn",
        source_id="88888",
        entity_type="entity",
        primary_name="Public Joint Stock Company Sberbank of Russia",
        programs=["RUSSIA-EO14024"],
        last_updated=datetime.now(timezone.utc),
        data_vintage=datetime.now(timezone.utc),
    )
    alias = EntityAlias(
        id=uuid.uuid4(),
        entity_id=entity.id,
        alias_name="Sberbank",
        alias_type="aka",
    )
    db_session.add(entity)
    db_session.add(alias)
    await db_session.flush()

    repo = EntityRepository(db_session)
    results = await repo.search("Sberbank")
    assert len(results) >= 1


async def test_search_returns_data_vintage(db_session, test_entity):
    """Every search result must include data_vintage metadata."""
    repo = EntityRepository(db_session)
    results = await repo.search("Test Bank")
    assert results[0].data_vintage is not None
```

---

## Layer 3: Router Tests

Router tests verify HTTP contracts: status codes, response shapes, and error handling.
They do NOT test business logic (that's the agent/repository layer's job).
Use the `client` fixture from conftest which has DB overridden.

```python
# tests/test_api/test_query.py
import pytest
from unittest.mock import AsyncMock, patch


async def test_query_returns_200(client):
    """POST /api/query should return 200 with valid query."""
    with patch("app.api.routes.query.run_agent_pipeline") as mock_pipeline:
        mock_pipeline.return_value = {
            "answer": "Sberbank is listed on the OFAC SDN list...",
            "citations": [{"source": "OFAC SDN", "reference": "Entry 12345"}],
            "data_vintage": {"ofac_sdn": "2026-05-14T00:00:00Z"},
            "jurisdictions_consulted": ["US"],
        }

        response = await client.post(
            "/api/query",
            json={"query": "Is Sberbank sanctioned?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "citations" in data
    assert "data_vintage" in data


async def test_query_with_empty_string_returns_422(client):
    """POST /api/query with empty query should return 422."""
    response = await client.post(
        "/api/query",
        json={"query": ""},
    )
    assert response.status_code == 422


async def test_entity_search_returns_200(client, test_entity):
    """GET /api/entity-search should return 200 with results."""
    response = await client.get("/api/entity-search", params={"query": "Test Bank"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
```

---

## Layer 4: Retrieval Tests

Test retrieval components with real PostgreSQL + pgvector where possible.

```python
# tests/test_retrieval/test_ensemble.py
async def test_ensemble_returns_ranked_results(db_session):
    """Ensemble retriever should return results ranked by RRF score."""
    # Insert test document chunks with embeddings
    ...
    retriever = EnsembleRetriever(db_session)
    results = await retriever.search("Russia oil price cap")
    assert len(results) > 0
    assert all(r.score >= results[i + 1].score for i, r in enumerate(results[:-1]))


async def test_ensemble_filters_by_jurisdiction(db_session):
    """Retriever should respect jurisdiction metadata filter."""
    ...
    retriever = EnsembleRetriever(db_session)
    results = await retriever.search("sanctions", jurisdiction="EU")
    assert all(r.jurisdiction == "EU" for r in results)
```

---

## What to Mock vs What to Use Real

| Component | Use Real | Use Mock |
|-----------|----------|----------|
| PostgreSQL + pgvector | Yes (testcontainers) | No |
| SQLite | No (never) | — |
| LLM API (Mistral/Ollama/vLLM) | No (costs money + flaky + non-deterministic) | Yes (AsyncMock) |
| Embedding model | Depends (mock for unit tests, real for eval) | — |
| FastAPI app | Yes (via AsyncClient) | No |
| DB session in routers | Yes (via dependency_overrides) | No |
| External HTTP calls (OFAC downloads) | No (flaky, rate-limited) | Yes (AsyncMock) |
