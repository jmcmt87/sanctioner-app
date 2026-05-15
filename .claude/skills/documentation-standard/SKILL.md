---
name: documentation-standards
description: >
  Use this skill whenever creating or updating documentation — README files, module
  docs, or inline documentation. Triggers on: completing a new module or package,
  finishing a development phase, when the user asks for documentation, when creating
  a new directory with an __init__.py, or when the auditor flags missing documentation.
  Also trigger when the user says "document this", "write a README", "I don't understand
  this module", or "how do I set this up". This skill defines what documentation exists,
  where it lives, and what it must contain — the Builder writes it as part of development,
  not as an afterthought.
---

# Documentation Standards

Documentation in this project follows a simple rule: every directory that a developer
would `cd` into should have a README.md explaining what's inside and how to work with it.

---

## When to Write Documentation

Documentation is part of the deliverable, not a separate task. Write or update docs:

- **When you create a new module/package** — write the module README before moving on.
- **When you finish a development phase** — update the project README with any new setup steps.
- **When you change how something works** — update the relevant README.
- **When you add a new data source** — update the ingestion README with the new source details.
- **When you add a new dependency** — update the relevant README's setup section if it requires configuration.

Do NOT write documentation speculatively for features that don't exist yet.

---

## Documentation Map

```
sanctions-screening-assistant/
├── README.md                          # Project README — setup, run, architecture overview
├── backend/
│   ├── README.md                      # Backend README — how to run, test, develop
│   ├── app/
│   │   ├── api/
│   │   │   └── README.md             # API routes — endpoint inventory, request/response shapes
│   │   ├── agent/
│   │   │   └── README.md             # Agent pipeline — node descriptions, routing logic, state schema
│   │   ├── db/
│   │   │   └── README.md             # Database — schema overview, repository inventory, migration guide
│   │   ├── retrieval/
│   │   │   └── README.md             # Retrieval — embedding model, search strategies, ensemble config
│   │   └── llm/
│   │       └── README.md             # LLM client — configuration, provider swap instructions
│   └── tests/
│       └── README.md                  # Testing — how to run tests, fixtures, eval harness
├── ingestion/
│   ├── README.md                      # Ingestion README — how to run, source inventory, freshness
│   └── pipeline/
│       ├── sources/
│       │   └── README.md             # Source parsers — inventory, adding a new source
│       └── chunking/
│           └── README.md             # Chunking — strategies per document type, configuration
├── frontend/
│   └── README.md                      # Frontend README — setup, components, build
└── infra/
    └── README.md                      # Infrastructure — AWS setup, deployment, environment config
```

Only create a README for a directory that exists and has code in it. Don't create
placeholder READMEs for empty directories.

---

## Template: Project README (Root)

The project README is the entry point. A new developer should be able to go from
`git clone` to a running local environment using only this file.

```markdown
# Sanctions Screening Assistant

AI-powered compliance research tool for dual-jurisdiction sanctions analysis
(US OFAC + EU Reg. 833/2014 + Germany BaFin/Bundesbank).

## What This Does

[2-3 sentences. What the tool is, who uses it, what problem it solves.
NOT a feature list — a problem statement.]

## Architecture Overview

[Brief description of the system: frontend → API → agent → database.
Link to CLAUDE.md for full architecture details. A simple diagram is welcome
but not required — don't over-produce.]

## Prerequisites

- Python 3.13+ (managed via uv)
- Docker + Docker Compose (for PostgreSQL + pgvector)
- Node.js 20+ and npm (for frontend)
- AWS CLI configured (for S3 access)

## Quick Start

### 1. Clone and set up environment variables

```bash
cp .env.example .env
# Edit .env with your values — see Environment Variables below
```

### 2. Start the database

```bash
docker compose up -d
```

### 3. Set up the backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### 4. Run data ingestion

```bash
cd ingestion
uv sync
uv run python scripts/ingest_all.py
```

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SSA_LLM_BASE_URL` | LLM API endpoint | `https://api.mistral.ai/v1` |
| `SSA_LLM_MODEL_NAME` | Model identifier | `mistral-large-latest` |
| `SSA_LLM_API_KEY` | API key (empty for local Ollama) | `sk-...` |
| `SSA_DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `SSA_S3_BUCKET` | S3 bucket for raw data | `sanctions-data-lake` |
| `SSA_EMBEDDING_MODEL` | Embedding model name | `BAAI/bge-m3` |

[Only list variables that currently exist. Update as new ones are added.]

## Project Structure

[Brief annotated tree — top two levels only. Link to CLAUDE.md for the full tree.]

## Running Tests

```bash
cd backend
uv run pytest
```

## Useful Links

- [CLAUDE.md](./CLAUDE.md) — Full project constitution (architecture, schema, conventions)
- [task_plan.md](./task_plan.md) — Development roadmap and task tracking
```

**Rules for the project README:**
- Keep it under 150 lines. It's a quickstart, not a manual.
- Every command must be copy-pasteable and work. Test them.
- Don't document features that don't exist yet.
- Update it when setup steps change (new env var, new dependency, new service).

---

## Template: Module README

Module READMEs explain what's inside a directory, how the pieces connect, and how
to work with them. They are written for a developer who understands the project
but is seeing this specific module for the first time.

```markdown
# [Module Name]

[One paragraph: what this module does, why it exists, and what role it plays
in the larger system. Be specific — "Handles entity and vessel lookups against
PostgreSQL" not "Database stuff."]

## What's Inside

| File | Purpose |
|------|---------|
| `file_one.py` | [One-line description] |
| `file_two.py` | [One-line description] |
| `file_three.py` | [One-line description] |

## How It Works

[2-4 paragraphs explaining the module's internal logic. How do the files connect?
What's the flow? What are the key decisions?]

## Dependencies

[What this module imports from other modules. Helps developers understand the
dependency graph.]

- Depends on: `app.db.models` (SQLAlchemy models), `app.config` (settings)
- Depended on by: `app.agent.nodes.sql_lookup` (entity search), `app.api.routes.entity` (API)

## Key Decisions

[2-3 bullet points explaining non-obvious design choices and why they were made.
These are the things a developer would ask "why did you do it this way?" about.]

## Adding / Modifying

[Brief instructions for the most common change someone would make to this module.
For a sources/ directory: "To add a new data source, create a new file following
the pattern in ofac_sdn.py and register it in runner.py."
For a nodes/ directory: "To add a new agent node, create a new file and add the
routing condition in graph.py."]
```

**Rules for module READMEs:**
- Max 80 lines. If it's longer, the module is doing too much or the README is over-explaining.
- The file inventory table must match the actual directory contents. If a file is missing
  from the table or the table lists a file that doesn't exist, the README is wrong.
- "How It Works" describes the current implementation, not the ideal design.
- "Key Decisions" captures the WHY, not the WHAT. The code shows what; the README shows why.
- Don't duplicate information from CLAUDE.md. Reference it: "See CLAUDE.md for the full schema."

---

## Template: Source Parsers README (ingestion/pipeline/sources/)

This is a specialized module README for the data sources directory, because it gets
new files more often than other modules and onboarding to a new source is a common task.

```markdown
# Source Parsers

Each file in this directory handles ingestion for one data source.
All parsers follow the six-step pattern defined in the ingestion-pipeline-patterns skill.

## Source Inventory

| Source | File | Format | Priority | Refresh | Status |
|--------|------|--------|----------|---------|--------|
| OFAC SDN List | `ofac_sdn.py` | CSV (pipe-delimited) | Essential | Daily | ✅ Implemented |
| EU Consolidated List | `eu_sanctions.py` | XML | Essential | Daily | ✅ Implemented |
| OFAC Non-SDN List | `ofac_nonsdn.py` | CSV | Recommended | Daily | ✅ Implemented |
| OFAC Enforcement Actions | `enforcement.py` | PDF (~293 files) | Essential | Monthly | ✅ Implemented |
| [Next source] | — | — | — | — | 🔲 Not started |

## Adding a New Source

1. Create a new file in this directory: `new_source.py`
2. Implement the standard function signature:
   ```python
   async def ingest_new_source(session, s3_client, config) -> IngestionResult:
   ```
3. Follow the six-step pattern: download → parse → validate → map → upsert → log
4. Register in `runner.py`:
   ```python
   REGISTERED_SOURCES["new_source"] = ingest_new_source
   ```
5. Update this README's source inventory table.

## Data Freshness

Last ingestion results per source:
[This section is updated automatically by the ingestion pipeline or manually after each run.]
```

---

## What NOT to Document

- **Implementation details that the code already shows.** Don't write "this function takes
  a string and returns a list" — that's what type hints are for.
- **Future features.** Don't document what the module will do someday. Document what it does now.
- **Internal design debates.** "We considered using Redis but chose PostgreSQL" belongs in
  a decision log or CLAUDE.md, not in a module README.
- **Setup steps that belong in the project README.** Module READMEs assume the environment is
  already running. They don't repeat `docker compose up` or `uv sync`.

---

## Style Rules

- Write in plain English. No marketing language. No filler ("In this section we will explore...").
- Use present tense ("Handles entity lookups", not "Will handle entity lookups").
- Code examples must be real and current. If the code changes, the example must change.
- Tables over prose for inventories and lists. Prose for explanations and reasoning.
- One blank line between sections. No decorative separators.
- File references use backticks: `ofac_sdn.py`, not *ofac_sdn.py* or ofac_sdn.py.

---

## Staleness Prevention

Documentation goes stale when it's disconnected from the code change that made it outdated.
To minimize this:

- When the Builder creates a new file in a module, it checks if the module README's file
  inventory table needs updating. If yes, update it in the same session.
- When the Builder adds a new environment variable, it adds it to the project README's
  environment variables table in the same session.
- When the Builder adds a new data source, it updates the source inventory table in
  `ingestion/pipeline/sources/README.md` in the same session.
- When the Builder changes how something is run (new command, different flags), it updates
  the relevant README's commands in the same session.

The rule is: **documentation updates happen in the same session as the code change
that triggers them, not in a separate "documentation pass."**