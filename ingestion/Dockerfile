FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/ /app/backend/
COPY ingestion/ /app/ingestion/

WORKDIR /app/ingestion
RUN uv sync --extra embeddings

CMD ["uv", "run", "python", "scripts/ingest_enforcement.py"]
