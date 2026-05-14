---
name: fastapi-testing
description: >
  FastAPI testing standards and test generation for Python projects. Use this skill
  whenever the agent finishes implementing a new service, router, schema, or any
  business logic — tests are NOT optional and must be written as part of the same task,
  not deferred. Also trigger when the user asks "write tests for this", "add test coverage",
  "how should I test this", or when auditing existing test quality.
  This skill enforces a specific stack (pytest + httpx AsyncClient + testcontainers)
  and a clear priority order for what to test first.
  IMPORTANT: Any implementation task is considered INCOMPLETE until its tests are written
  and passing. The agent must never mark a checklist item as done without its tests.
---

# FastAPI Testing Skill

You are enforcing testing standards for a Python/FastAPI project — the **Sanctions Screening
Assistant**. Your job is to ensure that every piece of new code has appropriate tests
written **in the same session**, using the approved stack and patterns defined here.

## The Non-Negotiable Rule

> **An implementation is not done until its tests are written and passing.**

When you finish implementing any of the following, you must immediately write tests before
moving to the next task:
- A new repository method (data access layer)
- A new router endpoint
- A new Pydantic schema with validation logic
- An agent node (preprocess, classify, sql_lookup, retrieve, synthesize, format_response)
- A retrieval component (embeddings, vector_store, bm25, ensemble)
- An ingestion source parser
- Any change to existing business logic

Do NOT ask the user if they want tests. Do NOT defer tests to "later". Write them now.

---

## When to Read Reference Files

- **Always read** `references/stack-setup.md` — approved tools, pytest config, fixture patterns.
- **Read** `references/test-patterns.md` — concrete patterns per layer (repository, router, agent node, retrieval).
- **Read** `references/sanctioner-app-priorities.md` — what to test first in this specific project,
  and how to mock the LLM client without hitting the real API.

---

## Test Writing Sequence

When implementing a new feature, follow this order:

1. **Write the implementation** (agent node, router, schema, repository, retrieval component)
2. **Immediately identify** what layer it belongs to (agent / router / repository / retrieval / ingestion)
3. **Read the corresponding pattern** from `references/test-patterns.md`
4. **Write the tests** before moving to the next file
5. **Run the tests** — confirm they pass before marking the task complete
6. **Update `progress.md`** with test results

---

## Output Format When Proposing Tests

When writing or proposing tests, always state:

### Test Plan for `[filename]`
- **Layer**: agent node / router / repository / retrieval / ingestion / schema
- **What is being tested**: list of behaviours, not implementation details
- **What is NOT tested here**: (e.g. "LLM response quality — not our responsibility to test")
- **Mocks needed**: list what needs to be mocked and why
- **Test file location**: `tests/[layer]/test_[filename].py`

Then write the tests.

---

## Coverage Philosophy

Do not aim for 100% coverage. Aim for **confidence coverage**:
- All happy paths
- The most likely error paths (invalid input, missing entity, LLM returning malformed JSON, empty retrieval results)
- Any logic with a conditional (`if/else`, type checks, confidence thresholds, intent routing)
- Data vintage propagation — verify vintage metadata flows through the pipeline

Do NOT write tests for:
- Pydantic's own validation mechanics (Pydantic is already tested by its authors)
- SQLAlchemy's ORM internals
- FastAPI's routing mechanics
- The quality of LLM responses (that's prompt engineering and the eval harness, not unit testing)
- pgvector's similarity search correctness (that's PostgreSQL's responsibility)
