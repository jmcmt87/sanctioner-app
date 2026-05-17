"""Make vector dimension configurable via SSA_EMBEDDING_DIM

Drops and recreates the embedding column + HNSW index with the dimension
from the SSA_EMBEDDING_DIM environment variable (defaults to 384 for dev).
Sets all existing embeddings to NULL so backfill_embeddings.py can re-embed
them with the new model.

Revision ID: b3d7e2f14a90
Revises: a06fa9eb0762
Create Date: 2026-05-17 12:00:00.000000

"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op

revision: str = "b3d7e2f14a90"
down_revision: str | None = "a06fa9eb0762"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = int(os.environ.get("SSA_EMBEDDING_DIM", "384"))


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute(
        f"ALTER TABLE document_chunks ADD COLUMN embedding vector({EMBEDDING_DIM})"
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN embedding vector(1024)"
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
