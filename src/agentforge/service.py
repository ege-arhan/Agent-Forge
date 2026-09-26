"""Application service: executes runs, benchmarks and experiments in the background.

Used by the HTTP API. Work runs as asyncio tasks in the API process, bounded by
``max_concurrent_runs``. Every state change is persisted, so clients poll the
database-backed API (or stream events) to follow progress. On startup, runs
left in progress by a previous process are marked as interrupted.

A distributed worker queue (e.g. Redis-backed) can later replace the in-process
task set behind the same interface.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from typing import Any

from agentforge.benchmarks.runner import BenchmarkRun, BenchmarkRunner
from agentforge.benchmarks.spec import BenchmarkSuite
from agentforge.core.config import AgentConfig
from agentforge.core.models import Run, RunStatus
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.experiments import Experiment, ExperimentRunner, ExperimentSpec
from agentforge.runtime.agent import AgentRuntime
from agentforge.runtime.events import EventBroadcaster, LoggingObserver
from agentforge.runtime.factory import prepare_run
from agentforge.settings import Settings
from agentforge.storage import Database, PersistenceObserver, RunRepository, SqlMemoryStore
from agentforge.storage.tracking import StorageRecorder

logger = logging.getLogger("agentforge.service")

CANCEL_GRACE_SECONDS = 5.0


class AgentForgeService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.runs = RunRepository(db)
        self.memory = SqlMemoryStore(db)
        self.broadcaster = EventBroadcaster()
        self.recorder = StorageRecorder(db, extra_observers=[self.broadcaster])
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_runs)
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._runtimes: dict[str, AgentRuntime] = {}

    async def startup(self) -> None:
        await self.db.create_all()
        interrupted = await self.runs.mark_interrupted()
        if interrupted:
            logger.warning("marked %d interrupted runs as failed", interrupted)

    async def shutdown(self) -> None:
        for runtime in self._runtimes.values():
            runtime.cancel()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, key: str, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro, name=key)
        self._tasks[key] = task

        def _done(t: asyncio.Task[Any]) -> None:
            self._tasks.pop(key, None)
            self._runtimes.pop(key, None)
            if not t.cancelled() and t.exception() is not None:
                logger.error("background task %s failed", key, exc_info=t.exception())

        task.add_done_callback(_done)

    # ------------------------------------------------------------------- runs
    async def start_run(
        self,
        config: AgentConfig,
        goal: str,
        *,
        agent_id: str | None = None,
        evaluators: list[EvaluatorSpec] | None = None,
        labels: dict[str, str] | None = None,
        parent_run_id: str | None = None,
    ) -> Run:
        prepared = prepare_run(
            config,
            goal,
            agent_id=agent_id,
            settings=self.settings,
            memory=self.memory,
            observers=[PersistenceObserver(self.runs), self.broadcaster, LoggingObserver()],
            labels=labels,
            parent_run_id=parent_run_id,
        )
        run = prepared.run
        run.evaluators = [spec.model_dump(mode="json") for spec in evaluators or []]
        await self.runs.save(run)
        self._runtimes[run.id] = prepared.runtime

        async def _execute() -> None:
            async with self._semaphore:
                await prepared.execute(evaluators)

        self._spawn(run.id, _execute())
        return run

    async def cancel_run(self, run_id: str) -> Run:
        run = await self.runs.get(run_id)
        if run.status.is_terminal:
            return run
        runtime = self._runtimes.get(run_id)
        task = self._tasks.get(run_id)
        if runtime is None or task is None:
            # Not running in this process (e.g. queued before a restart).
            run.status = RunStatus.CANCELLED
            await self.runs.save(run)
            return run
        runtime.cancel()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=CANCEL_GRACE_SECONDS)
        if not task.done():
            task.cancel()  # blocked in a model/tool call: interrupt it
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        return await self.runs.get(run_id)

    def is_active(self, key: str) -> bool:
        return key in self._tasks

    # ------------------------------------------------------------- benchmarks
    def _benchmark_runner(self) -> BenchmarkRunner:
        return BenchmarkRunner(self.settings, recorder=self.recorder, memory=None)

    async def start_benchmark(
        self,
        suite: BenchmarkSuite,
        config: AgentConfig,
        *,
        repeats: int | None = None,
        task_ids: list[str] | None = None,
    ) -> BenchmarkRun:
        if task_ids:
            for task_id in task_ids:
                suite.task(task_id)
        bench = BenchmarkRun(
            suite_id=suite.id,
            suite_name=suite.name,
            agent_name=config.name,
            agent_config=config,
            suite=suite,
            repeats=repeats or suite.repeats,
        )
        await self.recorder.save_benchmark(bench)

        async def _execute() -> None:
            async with self._semaphore:
                await self._benchmark_runner().run(
                    suite, config, repeats=repeats, task_ids=task_ids, bench=bench
                )

        self._spawn(bench.id, _execute())
        return bench

    async def start_experiment(
        self, spec: ExperimentSpec, suite: BenchmarkSuite, base: AgentConfig
    ) -> Experiment:
        from agentforge.experiments import variant_config

        for variant in spec.variants:
            variant_config(base, variant)  # validate before accepting
        experiment = Experiment(
            name=spec.name, description=spec.description, spec=spec, suite_id=suite.id
        )
        await self.recorder.save_experiment(experiment)
        runner = ExperimentRunner(self._benchmark_runner(), self.recorder)

        async def _execute() -> None:
            async with self._semaphore:
                await runner.run(spec, suite, base, experiment=experiment)

        self._spawn(experiment.id, _execute())
        return experiment
