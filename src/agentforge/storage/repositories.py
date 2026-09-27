"""Repositories translating between domain models and ORM rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, func, select

from agentforge.core.config import AgentConfig
from agentforge.core.errors import NotFoundError
from agentforge.core.ids import utcnow
from agentforge.core.models import Agent, Run, RunStatus
from agentforge.memory.base import MemoryRecord, MemoryScope, MemoryStore
from agentforge.storage.db import (
    AgentRow,
    Database,
    MemoryRow,
    RunRow,
    ToolCallRow,
)

TERMINAL_STATUSES = (
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.TIMED_OUT,
)


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json") if model is not None else None


class AgentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, config: AgentConfig) -> Agent:
        agent = Agent(config=config)
        async with self.db.transaction() as session:
            existing = await session.scalar(select(AgentRow.id).where(AgentRow.name == config.name))
            if existing:
                raise ValueError(f"an agent named '{config.name}' already exists")
            session.add(
                AgentRow(
                    id=agent.id,
                    name=config.name,
                    description=config.description,
                    config=config.model_dump(mode="json"),
                    version=agent.version,
                    created_at=agent.created_at,
                    updated_at=agent.updated_at,
                )
            )
        return agent

    async def update(self, agent_id: str, config: AgentConfig) -> Agent:
        async with self.db.transaction() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                raise NotFoundError(f"agent {agent_id} not found")
            if config.name != row.name:
                clash = await session.scalar(
                    select(AgentRow.id).where(AgentRow.name == config.name)
                )
                if clash:
                    raise ValueError(f"an agent named '{config.name}' already exists")
            row.name = config.name
            row.description = config.description
            row.config = config.model_dump(mode="json")
            row.version += 1
            row.updated_at = utcnow()
            return _agent(row)

    async def get(self, agent_id: str) -> Agent:
        async with self.db.session() as session:
            row = await session.get(AgentRow, agent_id)
        if row is None:
            raise NotFoundError(f"agent {agent_id} not found")
        return _agent(row)

    async def get_by_name(self, name: str) -> Agent | None:
        async with self.db.session() as session:
            row = await session.scalar(select(AgentRow).where(AgentRow.name == name))
        return _agent(row) if row else None

    async def list(self) -> list[Agent]:
        async with self.db.session() as session:
            rows = (await session.scalars(select(AgentRow).order_by(AgentRow.name))).all()
        return [_agent(r) for r in rows]

    async def delete(self, agent_id: str) -> None:
        async with self.db.transaction() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                raise NotFoundError(f"agent {agent_id} not found")
            await session.delete(row)


def _agent(row: AgentRow) -> Agent:
    return Agent(
        id=row.id,
        config=AgentConfig.model_validate(row.config),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass
class RunPage:
    items: list[Run]
    total: int


class RunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, run: Run, *, benchmark_run_id: str | None = None) -> None:
        values = _run_values(run)
        async with self.db.transaction() as session:
            row = await session.get(RunRow, run.id)
            if row is None:
                row = RunRow(id=run.id, benchmark_run_id=benchmark_run_id, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                if benchmark_run_id is not None:
                    row.benchmark_run_id = benchmark_run_id
            await session.flush()
            await session.execute(delete(ToolCallRow).where(ToolCallRow.run_id == run.id))
            for step in run.steps:
                for call in step.tool_calls:
                    session.add(
                        ToolCallRow(
                            run_id=run.id,
                            step_index=step.index,
                            call_id=call.id,
                            tool=call.tool,
                            status=call.status.value,
                            duration_ms=call.duration_ms,
                            created_at=call.started_at,
                        )
                    )

    async def get(self, run_id: str) -> Run:
        async with self.db.session() as session:
            row = await session.get(RunRow, run_id)
        if row is None:
            raise NotFoundError(f"run {run_id} not found")
        return _run(row)

    async def list(
        self,
        *,
        status: RunStatus | None = None,
        agent_id: str | None = None,
        benchmark_run_id: str | None = None,
        label: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RunPage:
        query = select(RunRow)
        count = select(func.count()).select_from(RunRow)
        filters = []
        if status is not None:
            filters.append(RunRow.status == status.value)
        if agent_id is not None:
            filters.append(RunRow.agent_id == agent_id)
        if benchmark_run_id is not None:
            filters.append(RunRow.benchmark_run_id == benchmark_run_id)
        if label is not None:
            filters.append(RunRow.labels[label].as_string().is_not(None))
        for condition in filters:
            query = query.where(condition)
            count = count.where(condition)
        query = (
            query.order_by(RunRow.created_at.desc(), RunRow.id.desc()).limit(limit).offset(offset)
        )
        async with self.db.session() as session:
            rows = (await session.scalars(query)).all()
            total = int(await session.scalar(count) or 0)
        return RunPage(items=[_run(r) for r in rows], total=total)

    async def mark_interrupted(self) -> int:
        """Fail runs left pending, running or awaiting approval by a previous process crash."""
        async with self.db.transaction() as session:
            rows = (
                await session.scalars(
                    select(RunRow).where(
                        RunRow.status.in_(
                            [
                                RunStatus.PENDING.value,
                                RunStatus.RUNNING.value,
                                RunStatus.AWAITING_APPROVAL.value,
                            ]
                        )
                    )
                )
            ).all()
            for row in rows:
                row.status = RunStatus.FAILED.value
                row.error = {
                    "type": "interrupted",
                    "message": "server restarted while the run was in progress",
                    "retryable": True,
                }
                row.finished_at = row.finished_at or utcnow()
            return len(rows)

    async def duration_summary(self) -> dict[str, dict[str, float]]:
        """Sum and count of run durations per terminal status (for metrics)."""
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(RunRow.status, func.sum(RunRow.duration_seconds), func.count())
                    .where(RunRow.duration_seconds.is_not(None))
                    .group_by(RunRow.status)
                )
            ).all()
        return {status: {"sum": float(total or 0.0), "count": int(n)} for status, total, n in rows}

    async def stats(self, *, since: datetime | None = None) -> dict[str, Any]:
        async with self.db.session() as session:
            status_query = select(RunRow.status, func.count()).group_by(RunRow.status)
            if since is not None:
                status_query = status_query.where(RunRow.created_at >= since)
            by_status = {s: int(n) for s, n in (await session.execute(status_query)).all()}

            eval_query = select(
                func.count(RunRow.passed),
                func.sum(case((RunRow.passed.is_(True), 1), else_=0)),
                func.avg(RunRow.score),
            ).where(RunRow.passed.is_not(None))
            if since is not None:
                eval_query = eval_query.where(RunRow.created_at >= since)
            evaluated, passed, avg_score = (await session.execute(eval_query)).one()

            cost_query = select(
                func.sum(RunRow.cost_usd),
                func.sum(case((RunRow.cost_usd.is_(None), 1), else_=0)),
                func.sum(RunRow.input_tokens),
                func.sum(RunRow.output_tokens),
            ).where(RunRow.status.in_([s.value for s in TERMINAL_STATUSES]))
            if since is not None:
                cost_query = cost_query.where(RunRow.created_at >= since)
            known_cost, unknown_cost, input_tokens, output_tokens = (
                await session.execute(cost_query)
            ).one()

            tool_query = select(ToolCallRow.tool, ToolCallRow.status, func.count()).group_by(
                ToolCallRow.tool, ToolCallRow.status
            )
            if since is not None:
                tool_query = tool_query.where(ToolCallRow.created_at >= since)
            tools: dict[str, dict[str, int]] = {}
            for tool, status, n in (await session.execute(tool_query)).all():
                tools.setdefault(tool, {})[status] = int(n)

        finished = sum(
            by_status.get(s.value, 0)
            for s in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TIMED_OUT)
        )
        return {
            "runs_by_status": by_status,
            "total_runs": sum(by_status.values()),
            "active_runs": (
                by_status.get("running", 0)
                + by_status.get("pending", 0)
                + by_status.get("awaiting_approval", 0)
            ),
            "completion_rate": (
                round(by_status.get("succeeded", 0) / finished, 4) if finished else None
            ),
            "evaluated_runs": int(evaluated or 0),
            "evaluation_pass_rate": (
                round(int(passed or 0) / int(evaluated), 4) if evaluated else None
            ),
            "mean_evaluation_score": round(float(avg_score), 4) if avg_score is not None else None,
            "tool_calls": tools,
            "known_cost_usd": round(float(known_cost), 6) if known_cost is not None else 0.0,
            "runs_with_unknown_cost": int(unknown_cost or 0),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
        }


def _run_values(run: Run) -> dict[str, Any]:
    return {
        "agent_id": run.agent_id,
        "agent_name": run.agent_name,
        "goal": run.goal,
        "status": run.status.value,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "result": run.result,
        "error": _dump(run.error),
        "usage": run.usage.model_dump(mode="json"),
        "evaluation": _dump(run.evaluation),
        "metrics": run.metrics.model_dump(mode="json"),
        "config": run.config.model_dump(mode="json"),
        "steps": [s.model_dump(mode="json") for s in run.steps],
        "plan": run.plan,
        "workspace": run.workspace,
        "labels": run.labels,
        "parent_run_id": run.parent_run_id,
        "passed": run.evaluation.passed if run.evaluation else None,
        "score": run.evaluation.score if run.evaluation else None,
        "provider": run.config.model.provider,
        "model": run.config.model.model,
        "evaluators": run.evaluators,
        "cost_usd": run.metrics.cost_usd,
        "duration_seconds": run.metrics.duration_seconds,
        "input_tokens": run.usage.input_tokens,
        "output_tokens": run.usage.output_tokens,
    }


def _run(row: RunRow) -> Run:
    return Run.model_validate(
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "agent_name": row.agent_name,
            "config": row.config,
            "goal": row.goal,
            "status": row.status,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "steps": row.steps,
            "plan": row.plan,
            "result": row.result,
            "error": row.error,
            "usage": row.usage,
            "evaluation": row.evaluation,
            "metrics": row.metrics,
            "workspace": row.workspace,
            "labels": row.labels,
            "parent_run_id": row.parent_run_id,
            "evaluators": row.evaluators or [],
        }
    )


class SqlMemoryStore(MemoryStore):
    """Persistent memory backed by the ``memories`` table (lexical search)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(self, record: MemoryRecord) -> MemoryRecord:
        async with self.db.transaction() as session:
            session.add(
                MemoryRow(
                    id=record.id,
                    scope=record.scope.value,
                    namespace=record.namespace,
                    content=record.content,
                    tags=record.tags,
                    meta=record.metadata,
                    created_at=record.created_at,
                )
            )
        return record

    async def list_records(
        self, scope: MemoryScope, namespace: str, *, limit: int = 100
    ) -> list[MemoryRecord]:
        async with self.db.session() as session:
            rows = (
                await session.scalars(
                    select(MemoryRow)
                    .where(MemoryRow.scope == scope.value, MemoryRow.namespace == namespace)
                    .order_by(MemoryRow.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            MemoryRecord(
                id=r.id,
                scope=MemoryScope(r.scope),
                namespace=r.namespace,
                content=r.content,
                tags=list(r.tags or []),
                metadata=dict(r.meta or {}),
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def delete(self, record_id: str) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(delete(MemoryRow).where(MemoryRow.id == record_id))
            return bool(getattr(result, "rowcount", 0))
