"""widen run status column

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27 07:03:40.591357
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # "awaiting_approval" (17 chars) no longer fits in the original String(16).
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.VARCHAR(length=16),
            type_=sa.String(length=24),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=24),
            type_=sa.VARCHAR(length=16),
            existing_nullable=False,
        )
