# Sanctions Screening Assistant

AI-powered compliance research tool for dual-jurisdiction sanctions analysis (US OFAC + EU Reg. 833/2014 + Germany BaFin/Bundesbank). Compliance analysts at European financial institutions use it to query sanctions data in natural language during alert investigations. Every response includes source citations and data vintage timestamps.

## Architecture Overview

```text
Analyst --> FastAPI API --> LangGraph Agent --> PostgreSQL (structured entities + pgvector)
                                           --> S3 (raw document storage)
```

The backend is a FastAPI async API backed by PostgreSQL 16 with pgvector. A separate ingestion pipeline downloads sanctions lists and regulatory documents, parses them into structured entity records, and loads them into the database. See [CLAUDE.md](./CLAUDE.md) for the full architecture, schema, and agent pipeline design.

## Prerequisites

- Python 3.13+ (managed via [uv](https://docs.astral.sh/uv/))
- Docker + Docker Compose (for PostgreSQL + pgvector)
- AWS CLI configured (for S3 access during data ingestion)

## Quick Start

### 1. Start the database

```bash
cd backend
docker compose up -d
```

### 2. Set up and run the backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`. Health check: `GET /health`.

### 3. Run data ingestion

```bash
cd ingestion
uv sync
# Place source data files in data/ (see ingestion/README.md for directory layout)
uv run python scripts/ingest_all.py
```

### 4. Run tests

```bash
cd backend && uv run pytest
cd ingestion && uv run pytest
```

## Environment Variables

All variables use the `SSA_` prefix. Set them in a `.env` file or export directly.

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `SSA_DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://postgres:postgres@localhost:5432/sanctions_db` |
| `SSA_LLM_BASE_URL` | LLM API endpoint | `https://api.mistral.ai/v1` |
| `SSA_LLM_MODEL_NAME` | Model identifier | `mistral-large-latest` |
| `SSA_LLM_API_KEY` | API key (empty for local Ollama) | `""` |
| `SSA_S3_BUCKET` | S3 bucket for raw data | `sanctions-data` |
| `SSA_S3_REGION` | AWS region | `eu-central-1` |
| `SSA_EMBEDDING_MODEL_NAME` | Embedding model | `BAAI/bge-m3` |
| `SSA_LOG_LEVEL` | Log level | `INFO` |

## Project Structure

```text
sanctions-screening-assistant/
├── backend/             # FastAPI app, database models, agent pipeline
│   ├── app/             # Application code (api/, agent/, db/, retrieval/, llm/)
│   ├── alembic/         # Database migrations
│   └── tests/           # Backend test suite
├── ingestion/           # Data ingestion pipeline
│   ├── pipeline/        # Parsers, loaders, upsert logic, runner
│   ├── scripts/         # CLI entry points for ingestion
│   └── tests/           # Ingestion test suite (110 tests)
├── frontend/            # React + TypeScript (not yet started)
├── infra/               # Terraform, production Docker Compose
├── CLAUDE.md            # Full project constitution
└── task_plan.md         # Development roadmap
```

## Useful Links

- [CLAUDE.md](./CLAUDE.md) -- Full project constitution (architecture, schema, conventions)
- [task_plan.md](./task_plan.md) -- Development roadmap and task tracking
