"""Persistence for benchmark runs and experiments."""

from __future__ import annotations

from sqlalchemy import select

from agentforge.benchmarks.runner import BenchmarkRecorder, BenchmarkRun
from agentforge.core.errors import NotFoundError
from agentforge.experiments import Experiment, ExperimentRecorder
from agentforge.runtime.events import RunObserver
from agentforge.storage.db import BenchmarkRunRow, Database, ExperimentRow
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
        }
        async with self.db.transaction() as session:
            row = await session.get(BenchmarkRunRow, bench.id)
            if row is None:
                session.add(BenchmarkRunRow(id=bench.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def get(self, bench_id: str) -> BenchmarkRun:
        async with self.db.session() as session:
            row = await session.get(BenchmarkRunRow, bench_id)
        if row is None:
            raise NotFoundError(f"benchmark run {bench_id} not found")
        return _bench(row)

    async def list(
        self, *, suite_id: str | None = None, experiment_id: str | None = None, limit: int = 50
    ) -> list[BenchmarkRun]:
        query = select(BenchmarkRunRow).order_by(BenchmarkRunRow.created_at.desc()).limit(limit)
        if suite_id:
            query = query.where(BenchmarkRunRow.suite_id == suite_id)
        if experiment_id:
            query = query.where(BenchmarkRunRow.experiment_id == experiment_id)
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
