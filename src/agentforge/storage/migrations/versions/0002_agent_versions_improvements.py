"""agent version history, benchmark provenance and improvement cycles

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26 21:00:00

- ``agent_versions``: immutable config snapshot per stored agent version.
  Existing agents get one row for their current version (earlier versions were
  never stored, so they cannot be reconstructed).
- ``benchmark_runs.agent_id`` / ``agent_version``: which stored agent version a
  benchmark ran (NULL for ad-hoc configs and older rows).
- ``benchmark_runs.result_class``: ``offline`` (scripted provider) or ``real``,
  backfilled from the stored agent config.
- ``improvement_cycles``: the agent improvement loop history.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import agentforge.storage.db

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OFFLINE_PROVIDERS = ("scripted",)


def _json() -> Any:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", _json(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("improvement_id", sa.String(length=64), nullable=True),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_version"),
    )
    with op.batch_alter_table("agent_versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_versions_agent_id"), ["agent_id"], unique=False)

    op.create_table(
        "improvement_cycles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("suite_id", sa.String(length=128), nullable=False),
        sa.Column("result_class", sa.String(length=16), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("to_version", sa.Integer(), nullable=True),
        sa.Column("baseline_benchmark_run_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_benchmark_run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("data", _json(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("improvement_cycles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_improvement_cycles_agent_id"), ["agent_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_improvement_cycles_created_at"), ["created_at"], unique=False
        )

    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("agent_version", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("result_class", sa.String(length=16), nullable=False, server_default="real")
        )
        batch_op.create_index(batch_op.f("ix_benchmark_runs_agent_id"), ["agent_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_benchmark_runs_result_class"), ["result_class"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_benchmark_runs_agent_id_agents", "agents", ["agent_id"], ["id"], ondelete="SET NULL"
        )

    _backfill()

    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        batch_op.alter_column("result_class", server_default=None)


def _backfill() -> None:
    bind = op.get_bind()
    agents = sa.table(
        "agents",
        sa.column("id", sa.String()),
        sa.column("config", sa.JSON()),
        sa.column("version", sa.Integer()),
        sa.column("updated_at", agentforge.storage.db.UTCDateTime()),
    )
    versions = sa.table(
        "agent_versions",
        sa.column("agent_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("config", sa.JSON()),
        sa.column("source", sa.String()),
        sa.column("change_summary", sa.Text()),
        sa.column("created_at", agentforge.storage.db.UTCDateTime()),
    )
    for agent_id, config, version, updated_at in bind.execute(
        sa.select(agents.c.id, agents.c.config, agents.c.version, agents.c.updated_at)
    ).all():
        bind.execute(
            versions.insert().values(
                agent_id=agent_id,
                version=version,
                config=config,
                source="created" if version == 1 else "updated",
                change_summary=""
                if version == 1
                else "Recorded when version history was introduced; earlier versions "
                "were not stored.",
                created_at=updated_at,
            )
        )

    benches = sa.table(
        "benchmark_runs",
        sa.column("id", sa.String()),
        sa.column("agent_config", sa.JSON()),
        sa.column("result_class", sa.String()),
    )
    for bench_id, config in bind.execute(sa.select(benches.c.id, benches.c.agent_config)).all():
        provider = ((config or {}).get("model") or {}).get("provider")
        if provider in OFFLINE_PROVIDERS:
            bind.execute(
                benches.update().where(benches.c.id == bench_id).values(result_class="offline")
            )


def downgrade() -> None:
    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_benchmark_runs_agent_id_agents", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_benchmark_runs_result_class"))
        batch_op.drop_index(batch_op.f("ix_benchmark_runs_agent_id"))
        batch_op.drop_column("result_class")
        batch_op.drop_column("agent_version")
        batch_op.drop_column("agent_id")
    with op.batch_alter_table("improvement_cycles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_improvement_cycles_created_at"))
        batch_op.drop_index(batch_op.f("ix_improvement_cycles_agent_id"))
    op.drop_table("improvement_cycles")
    with op.batch_alter_table("agent_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_versions_agent_id"))
    op.drop_table("agent_versions")
