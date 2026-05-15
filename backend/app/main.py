from __future__ import annotations

from fastapi import FastAPI

from app.logging import setup_logging

setup_logging()

app = FastAPI(
    title="Sanctions Screening Assistant",
    description="AI-powered compliance research tool for dual-jurisdiction sanctions analysis",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
