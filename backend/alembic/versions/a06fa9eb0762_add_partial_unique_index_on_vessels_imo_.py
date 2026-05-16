"""Add partial unique index on vessels.imo_number

Revision ID: a06fa9eb0762
Revises: 930864a558eb
Create Date: 2026-05-16 19:55:23.723161

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a06fa9eb0762"
down_revision: str | None = "930864a558eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_vessels_imo_entity_unique",
        "vessels",
        ["imo_number", "entity_id"],
        unique=True,
        postgresql_where=sa.text("imo_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vessels_imo_entity_unique",
        table_name="vessels",
        postgresql_where=sa.text("imo_number IS NOT NULL"),
    )
