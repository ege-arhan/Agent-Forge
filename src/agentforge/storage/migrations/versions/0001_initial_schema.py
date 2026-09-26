"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-26 18:47:26.887103
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import agentforge.storage.db

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "config",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agents_name"), ["name"], unique=True)

    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("suite_id", sa.String(length=128), nullable=False),
        sa.Column("suite_name", sa.String(length=200), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("finished_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("repeats", sa.Integer(), nullable=False),
        sa.Column(
            "agent_config",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "suite",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "results",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("experiment_id", sa.String(length=64), nullable=True),
        sa.Column("variant", sa.String(length=128), nullable=True),
        sa.Column(
            "environment",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_benchmark_runs_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_benchmark_runs_experiment_id"), ["experiment_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_benchmark_runs_suite_id"), ["suite_id"], unique=False)

    op.create_table(
        "experiments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("finished_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column(
            "spec",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_experiments_created_at"), ["created_at"], unique=False)

    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memories", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memories_created_at"), ["created_at"], unique=False)
        batch_op.create_index("ix_memories_scope_ns", ["scope", "namespace"], unique=False)

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("started_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("finished_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "error",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "usage",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "evaluation",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "metrics",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "config",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "steps",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "plan",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("workspace", sa.Text(), nullable=True),
        sa.Column(
            "labels",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("parent_run_id", sa.String(length=64), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("benchmark_run_id", sa.String(length=64), nullable=True),
        sa.Column(
            "evaluators",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_agent_id"), ["agent_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_agent_name"), ["agent_name"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_runs_benchmark_run_id"), ["benchmark_run_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_runs_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_status"), ["status"], unique=False)

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", agentforge.storage.db.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tool_calls", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tool_calls_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_tool_calls_tool_status", ["tool", "status"], unique=False)


def downgrade() -> None:

    with op.batch_alter_table("tool_calls", schema=None) as batch_op:
        batch_op.drop_index("ix_tool_calls_tool_status")
        batch_op.drop_index(batch_op.f("ix_tool_calls_run_id"))

    op.drop_table("tool_calls")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_status"))
        batch_op.drop_index(batch_op.f("ix_runs_created_at"))
        batch_op.drop_index(batch_op.f("ix_runs_benchmark_run_id"))
        batch_op.drop_index(batch_op.f("ix_runs_agent_name"))
        batch_op.drop_index(batch_op.f("ix_runs_agent_id"))

    op.drop_table("runs")
    with op.batch_alter_table("memories", schema=None) as batch_op:
        batch_op.drop_index("ix_memories_scope_ns")
        batch_op.drop_index(batch_op.f("ix_memories_created_at"))

    op.drop_table("memories")
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_experiments_created_at"))

    op.drop_table("experiments")
    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_benchmark_runs_suite_id"))
        batch_op.drop_index(batch_op.f("ix_benchmark_runs_experiment_id"))
        batch_op.drop_index(batch_op.f("ix_benchmark_runs_created_at"))

    op.drop_table("benchmark_runs")
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agents_name"))

    op.drop_table("agents")
