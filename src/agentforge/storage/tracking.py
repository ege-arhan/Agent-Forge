"""Persistence for benchmark runs and experiments."""

from __future__ import annotations

from sqlalchemy import select, update

from agentforge.benchmarks.runner import BenchmarkRecorder, BenchmarkRun
from agentforge.core.errors import NotFoundError
from agentforge.core.ids import utcnow
from agentforge.core.models import RunStatus
from agentforge.experiments import Experiment, ExperimentRecorder
from agentforge.improvement.cycle import CycleStatus, ImprovementCycle
from agentforge.runtime.events import RunObserver
from agentforge.storage.db import BenchmarkRunRow, Database, ExperimentRow, ImprovementCycleRow
from agentforge.storage.repositories import RunRepository


class BenchmarkRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, bench: BenchmarkRun) -> None:
        values = {
            "suite_id": bench.suite_id,
            "suite_name": bench.suite_name,
            "agent_name": bench.agent_name,
            "status": bench.status.value,
            "created_at": bench.created_at,
            "finished_at": bench.finished_at,
            "repeats": bench.repeats,
            "agent_config": bench.agent_config.model_dump(mode="json"),
            "suite": bench.suite.model_dump(mode="json"),
            "summary": bench.summary.model_dump(mode="json") if bench.summary else None,
            "results": [r.model_dump(mode="json") for r in bench.results],
            "experiment_id": bench.experiment_id,
            "variant": bench.variant,
            "environment": bench.environment,
            "agent_id": bench.agent_id,
            "agent_version": bench.agent_version,
            "result_class": bench.result_class.value,
        }
        async with self.db.transaction() as session:
            row = await session.get(BenchmarkRunRow, bench.id)
            if row is None:
                session.add(BenchmarkRunRow(id=bench.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def mark_interrupted(self) -> int:
        """Fail benchmark runs left pending/running by a previous process."""
        async with self.db.transaction() as session:
            rows = (
                await session.scalars(
                    select(BenchmarkRunRow).where(
                        BenchmarkRunRow.status.in_(
                            [RunStatus.PENDING.value, RunStatus.RUNNING.value]
                        )
                    )
                )
            ).all()
            for row in rows:
                row.status = RunStatus.FAILED.value
                row.finished_at = row.finished_at or utcnow()
            return len(rows)

    async def get(self, bench_id: str) -> BenchmarkRun:
        async with self.db.session() as session:
            row = await session.get(BenchmarkRunRow, bench_id)
        if row is None:
            raise NotFoundError(f"benchmark run {bench_id} not found")
        return _bench(row)

    async def list(
        self,
        *,
        suite_id: str | None = None,
        experiment_id: str | None = None,
        agent_id: str | None = None,
        result_class: str | None = None,
        limit: int = 50,
    ) -> list[BenchmarkRun]:
        query = select(BenchmarkRunRow).order_by(BenchmarkRunRow.created_at.desc()).limit(limit)
        if suite_id:
            query = query.where(BenchmarkRunRow.suite_id == suite_id)
        if experiment_id:
            query = query.where(BenchmarkRunRow.experiment_id == experiment_id)
        if agent_id:
            query = query.where(BenchmarkRunRow.agent_id == agent_id)
        if result_class:
            query = query.where(BenchmarkRunRow.result_class == result_class)
        async with self.db.session() as session:
            rows = (await session.scalars(query)).all()
        return [_bench(r) for r in rows]


def _bench(row: BenchmarkRunRow) -> BenchmarkRun:
    return BenchmarkRun.model_validate(
        {
            "id": row.id,
            "suite_id": row.suite_id,
            "suite_name": row.suite_name,
            "agent_name": row.agent_name,
            "agent_config": row.agent_config,
            "suite": row.suite,
            "status": row.status,
            "created_at": row.created_at,
            "finished_at": row.finished_at,
            "repeats": row.repeats,
            "results": row.results,
            "summary": row.summary,
            "experiment_id": row.experiment_id,
            "variant": row.variant,
            "environment": row.environment,
            "agent_id": row.agent_id,
            "agent_version": row.agent_version,
        }
    )


class ExperimentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, experiment: Experiment) -> None:
        values = {
            "name": experiment.name,
            "description": experiment.description,
            "status": experiment.status.value,
            "created_at": experiment.created_at,
            "finished_at": experiment.finished_at,
            "spec": experiment.spec.model_dump(mode="json"),
            "summary": {
                "suite_id": experiment.suite_id,
                "variants": [v.model_dump(mode="json") for v in experiment.variants],
            },
        }
        async with self.db.transaction() as session:
            row = await session.get(ExperimentRow, experiment.id)
            if row is None:
                session.add(ExperimentRow(id=experiment.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def get(self, experiment_id: str) -> Experiment:
        async with self.db.session() as session:
            row = await session.get(ExperimentRow, experiment_id)
        if row is None:
            raise NotFoundError(f"experiment {experiment_id} not found")
        return _experiment(row)

    async def list(self, *, limit: int = 50) -> list[Experiment]:
        async with self.db.session() as session:
            rows = (
                await session.scalars(
                    select(ExperimentRow).order_by(ExperimentRow.created_at.desc()).limit(limit)
                )
            ).all()
        return [_experiment(r) for r in rows]


def _experiment(row: ExperimentRow) -> Experiment:
    summary = row.summary or {}
    return Experiment.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "status": row.status,
            "created_at": row.created_at,
            "finished_at": row.finished_at,
            "spec": row.spec,
            "suite_id": summary.get("suite_id", ""),
            "variants": summary.get("variants", []),
        }
    )


_CYCLE_COLUMNS = (
    "agent_id",
    "status",
    "suite_id",
    "result_class",
    "from_version",
    "to_version",
    "baseline_benchmark_run_id",
    "candidate_benchmark_run_id",
    "created_at",
    "updated_at",
)


class ImprovementRepository:
    """Improvement cycles (the agent improvement history)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, cycle: ImprovementCycle) -> None:
        dumped = cycle.model_dump(mode="json")
        values = {key: getattr(cycle, key) for key in _CYCLE_COLUMNS}
        values["status"] = cycle.status.value
        values["result_class"] = cycle.result_class.value
        values["data"] = {k: v for k, v in dumped.items() if k not in _CYCLE_COLUMNS and k != "id"}
        async with self.db.transaction() as session:
            row = await session.get(ImprovementCycleRow, cycle.id)
            if row is None:
                session.add(ImprovementCycleRow(id=cycle.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def claim(self, cycle_id: str, *, expected: CycleStatus, new: CycleStatus) -> bool:
        """Atomically move a cycle from ``expected`` to ``new``; False if it was not ``expected``.

        A conditional UPDATE, so of two concurrent requests exactly one wins.
        """
        async with self.db.transaction() as session:
            result = await session.execute(
                update(ImprovementCycleRow)
                .where(
                    ImprovementCycleRow.id == cycle_id,
                    ImprovementCycleRow.status == expected.value,
                )
                .values(status=new.value, updated_at=utcnow())
            )
        return bool(getattr(result, "rowcount", 0) == 1)

    async def get(self, cycle_id: str) -> ImprovementCycle:
        async with self.db.session() as session:
            row = await session.get(ImprovementCycleRow, cycle_id)
        if row is None:
            raise NotFoundError(f"improvement cycle {cycle_id} not found")
        return _cycle(row)

    async def mark_interrupted(self) -> int:
        """Fail cycles whose evaluation was running when a previous process stopped."""
        async with self.db.session() as session:
            rows = (
                await session.scalars(
                    select(ImprovementCycleRow).where(
                        ImprovementCycleRow.status == CycleStatus.EVALUATING.value
                    )
                )
            ).all()
        for row in rows:
            cycle = _cycle(row)
            cycle.status = CycleStatus.FAILED
            cycle.error = "the server restarted while the evaluation was running"
            cycle.updated_at = utcnow()
            await self.save(cycle)
        return len(rows)

    async def list(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> list[ImprovementCycle]:
        query = (
            select(ImprovementCycleRow)
            .order_by(ImprovementCycleRow.created_at.desc(), ImprovementCycleRow.id.desc())
            .limit(limit)
        )
        if agent_id:
            query = query.where(ImprovementCycleRow.agent_id == agent_id)
        async with self.db.session() as session:
            rows = (await session.scalars(query)).all()
        return [_cycle(r) for r in rows]


def _cycle(row: ImprovementCycleRow) -> ImprovementCycle:
    data = dict(row.data or {})
    data.update({key: getattr(row, key) for key in _CYCLE_COLUMNS})
    data["id"] = row.id
    return ImprovementCycle.model_validate(data)


class StorageRecorder(BenchmarkRecorder, ExperimentRecorder):
    """Persists benchmark runs, experiments and every underlying agent run."""

    def __init__(self, db: Database, extra_observers: list[RunObserver] | None = None) -> None:
        self.runs = RunRepository(db)
        self.benchmarks = BenchmarkRepository(db)
        self.experiments = ExperimentRepository(db)
        self._extra = list(extra_observers or [])

    async def save_benchmark(self, bench: BenchmarkRun) -> None:
        await self.benchmarks.save(bench)

    async def save_experiment(self, experiment: Experiment) -> None:
        await self.experiments.save(experiment)

    def run_observers(self, bench: BenchmarkRun) -> list[RunObserver]:
        from agentforge.storage import PersistenceObserver

        return [PersistenceObserver(self.runs, benchmark_run_id=bench.id), *self._extra]
