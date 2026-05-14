Run a full architecture audit of the backend codebase using the architecture auditor agent.

1. Switch to the architecture auditor agent: use `.claude/agents/architecture-auditor.md`
2. Audit scope: `backend/app/`, `ingestion/pipeline/`, `backend/alembic/`, `backend/tests/`
3. Check against `claude.md` — schema design, agent pipeline architecture, retrieval pipeline, LLM abstraction, data vintage compliance, citation enforcement
4. Output a prioritized fix list with section verdicts
5. Write the full report to `.tmp/audit_report_{date}.md` where `{date}` is today's date (YYYY-MM-DD)
6. Show me a summary of the verdict and any critical/warning items
