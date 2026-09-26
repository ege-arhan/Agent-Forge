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
import os
from collections.abc import Callable, Coroutine
from typing import Any

import httpx

from agentforge.benchmarks.runner import BenchmarkRun, BenchmarkRunner
from agentforge.benchmarks.spec import BenchmarkSuite
from agentforge.core.config import AgentConfig
from agentforge.core.errors import CapacityError
from agentforge.core.models import Run, RunStatus
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.experiments import Experiment, ExperimentRunner, ExperimentSpec
from agentforge.policy import ServerPolicy
from agentforge.runtime.agent import AgentRuntime
from agentforge.runtime.events import EventBroadcaster, LoggingObserver, RunObserver
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
        self.tracing: RunObserver | None = None
        if settings.otel_enabled:
            from agentforge.observability.otel import configure_tracing

            self.tracing = configure_tracing()
        extra: list[RunObserver] = [self.broadcaster]
        if self.tracing is not None:
            extra.append(self.tracing)
        self.recorder = StorageRecorder(db, extra_observers=extra)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_runs)
        self.policy = ServerPolicy(settings)
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._runtimes: dict[str, AgentRuntime] = {}
        # Test/mirror hooks (never exposed through the API: the GitHub token is
        # sent to the clone remote, so callers must not choose it).
        self.github_transport: httpx.AsyncBaseTransport | None = None
        self.github_remote_for: Callable[[str], str] | None = None

    def _run_observers(self) -> list[RunObserver]:
        observers: list[RunObserver] = [
            PersistenceObserver(self.runs),
            self.broadcaster,
            LoggingObserver(),
        ]
        if self.tracing is not None:
            observers.append(self.tracing)
        return observers

    async def startup(self) -> None:
        await self.db.migrate()
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

    def _admit(self) -> None:
        if len(self._tasks) >= self.settings.max_queued_runs:
            raise CapacityError(
                f"server is at capacity ({len(self._tasks)} queued or running tasks); retry later"
            )

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
        self.policy.check_agent(config)
        self.policy.check_evaluators(evaluators or [])
        self._admit()
        prepared = prepare_run(
            config,
            goal,
            agent_id=agent_id,
            settings=self.settings,
            memory=self.memory,
            observers=self._run_observers(),
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
        self.policy.check_agent(config)
        self._admit()
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
            self.policy.check_agent(variant_config(base, variant))  # validate before accepting
        self._admit()
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

    # ----------------------------------------------------------------- github
    def github_token(self) -> str | None:
        return os.environ.get(self.settings.github_token_env)

    def github_client(self) -> Any:
        from agentforge.integrations.github.client import GitHubClient

        return GitHubClient(self.github_token(), transport=self.github_transport)

    async def start_github_task(
        self,
        *,
        repo: str,
        issue_number: int,
        config: AgentConfig,
        agent_id: str | None = None,
        base_branch: str | None = None,
        test_command: str | None = None,
        push: bool = False,
        open_pr: bool = False,
        allow_failing: bool = False,
    ) -> Run:
        from agentforge.core.models import ErrorInfo
        from agentforge.integrations.github.client import parse_repo
        from agentforge.integrations.github.workflow import (
            GitHubWorkflowError,
            IssueTaskRequest,
            solve_issue,
        )

        parse_repo(repo)
        self.policy.check_agent(config)
        self._admit()
        if open_pr and not push:
            raise GitHubWorkflowError("open_pr requires push")
        run = Run(
            agent_id=agent_id,
            agent_name=config.name,
            config=config,
            goal=f"Resolve GitHub issue {repo}#{issue_number}",
            labels={**config.labels, "github_repo": repo, "github_issue": str(issue_number)},
        )
        await self.runs.save(run)
        request = IssueTaskRequest(
            repo=repo,
            issue_number=issue_number,
            config=config,
            base_branch=base_branch,
            test_command=test_command,
            push=push,
            open_pr=open_pr,
            allow_failing=allow_failing,
            agent_id=agent_id,
            remote_url=self.github_remote_for(repo) if self.github_remote_for else None,
        )

        async def _execute() -> None:
            async with self._semaphore:
                try:
                    async with self.github_client() as client:
                        result = await solve_issue(
                            request,
                            settings=self.settings,
                            client=client,
                            token=self.github_token(),
                            observers=self._run_observers(),
                            memory=self.memory,
                            run=run,
                        )
                    if result.pr_url:
                        run.labels["pr_url"] = result.pr_url
                    if result.pushed:
                        run.labels["pushed"] = "true"
                    run.labels["commits"] = str(result.commits)
                    await self.runs.save(run)
                except Exception as exc:
                    logger.warning("github task for %s#%s failed: %s", repo, issue_number, exc)
                    if not run.status.is_terminal:
                        run.status = RunStatus.FAILED
                    run.error = run.error or ErrorInfo(
                        type="github", message=getattr(exc, "message", str(exc))
                    )
                    await self.runs.save(run)

        self._spawn(run.id, _execute())
        return run
