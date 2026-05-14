# Sanctions Screening Assistant

AI-powered compliance research tool for dual-jurisdiction sanctions analysis (US OFAC + EU Reg. 833/2014 + Germany BaFin/Bundesbank).

See `CLAUDE.md` for full project documentation, architecture, and development workflow.

## Quick Start

```bash
# Start PostgreSQL
cd backend && docker compose up -d

# Install backend dependencies
cd backend && uv sync

# Run migrations
cd backend && uv run alembic upgrade head

# Start the API
cd backend && uv run uvicorn app.main:app --reload
```
