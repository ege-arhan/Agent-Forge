"""Benchmark execution: every task x repeat is a normal, fully recorded run."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agentforge import __version__
from agentforge.benchmarks.spec import BenchmarkSuite, BenchmarkTask
from agentforge.benchmarks.stats import mean, rounded, stddev, wilson_interval
from agentforge.core.config import AgentConfig
from agentforge.core.errors import BenchmarkError
from agentforge.core.ids import new_id, utcnow
from agentforge.core.models import Run, RunStatus
from agentforge.memory.base import MemoryStore
from agentforge.runtime.events import RunObserver
from agentforge.runtime.factory import prepare_run
from agentforge.settings import Settings

logger = logging.getLogger("agentforge.benchmarks")


class TaskRunResult(BaseModel):
    task_id: str
    repeat: int
    run_id: str
    status: RunStatus
    passed: bool
    score: float
    duration_seconds: float | None = None
    steps: int = 0
    tool_calls: int = 0
    tool_success_rate: float | None = None
    llm_retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    error: str | None = None


class TaskSummary(BaseModel):
    task_id: str
    runs: int
    passed: int
    pass_rate: float
    mean_score: float
    score_stddev: float | None = None
    mean_duration_seconds: float | None = None
    mean_steps: float | None = None


class BenchmarkSummary(BaseModel):
    runs: int
    passed: int
    pass_rate: float
    pass_rate_ci95: tuple[float, float] | None = None
    mean_score: float
    score_stddev: float | None = None
    mean_duration_seconds: float | None = None
    mean_steps: float | None = None
    mean_tool_success_rate: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float | None = None
    errors: int = 0
    tasks: list[TaskSummary] = Field(default_factory=list)


class BenchmarkRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("bench"))
    suite_id: str
    suite_name: str
    agent_name: str
    agent_config: AgentConfig
    suite: BenchmarkSuite
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    repeats: int = 1
    results: list[TaskRunResult] = Field(default_factory=list)
    summary: BenchmarkSummary | None = None
    experiment_id: str | None = None
    variant: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)


def environment_info(config: AgentConfig) -> dict[str, Any]:
    return {
        "agentforge_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "provider": config.model.provider,
        "model": config.model.model,
        "sandbox": config.sandbox.kind.value,
    }


def task_config(config: AgentConfig, suite: BenchmarkSuite, task: BenchmarkTask) -> AgentConfig:
    """Effective config for one task.

    Task/suite limits are *caps*: an agent configured with a tighter budget
    keeps it, so experiments can vary limits.
    """
    task_timeout = task.timeout_seconds or suite.defaults.timeout_seconds
    task_steps = task.max_steps or suite.defaults.max_steps
    limits = config.limits.model_copy(
        update={
            "timeout_seconds": min(config.limits.timeout_seconds, task_timeout),
            "max_steps": min(config.limits.max_steps, task_steps),
        }
    )
    update: dict[str, Any] = {"limits": limits}
    if task.allowed_tools is not None:
        update["tools"] = list(task.allowed_tools)
    return config.model_copy(update=update)


def result_from_run(task_id: str, repeat: int, run: Run) -> TaskRunResult:
    evaluation = run.evaluation
    m = run.metrics
    return TaskRunResult(
        task_id=task_id,
        repeat=repeat,
        run_id=run.id,
        status=run.status,
        passed=bool(evaluation and evaluation.passed),
        score=evaluation.score if evaluation else 0.0,
        duration_seconds=m.duration_seconds,
        steps=m.steps,
        tool_calls=m.tool_calls,
        tool_success_rate=m.tool_success_rate,
        llm_retries=m.llm_retries,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        cost_usd=m.cost_usd,
        error=run.error.message if run.error else None,
    )


def summarize(results: list[TaskRunResult], task_ids: list[str]) -> BenchmarkSummary:
    passed = sum(1 for r in results if r.passed)
    scores = [r.score for r in results]
    durations = [r.duration_seconds for r in results if r.duration_seconds is not None]
    tool_rates = [r.tool_success_rate for r in results if r.tool_success_rate is not None]
    costs = [r.cost_usd for r in results]
    ci = wilson_interval(passed, len(results))
    tasks: list[TaskSummary] = []
    for task_id in task_ids:
        subset = [r for r in results if r.task_id == task_id]
        if not subset:
            continue
        task_passed = sum(1 for r in subset if r.passed)
        task_durations = [r.duration_seconds for r in subset if r.duration_seconds is not None]
        tasks.append(
            TaskSummary(
                task_id=task_id,
                runs=len(subset),
                passed=task_passed,
                pass_rate=round(task_passed / len(subset), 4),
                mean_score=round(mean([r.score for r in subset]) or 0.0, 4),
                score_stddev=rounded(stddev([r.score for r in subset])),
                mean_duration_seconds=rounded(mean(task_durations), 3),
                mean_steps=rounded(mean([float(r.steps) for r in subset]), 2),
            )
        )
    return BenchmarkSummary(
        runs=len(results),
        passed=passed,
        pass_rate=round(passed / len(results), 4) if results else 0.0,
        pass_rate_ci95=(round(ci[0], 4), round(ci[1], 4)) if ci else None,
        mean_score=round(mean(scores) or 0.0, 4),
        score_stddev=rounded(stddev(scores)),
        mean_duration_seconds=rounded(mean(durations), 3),
        mean_steps=rounded(mean([float(r.steps) for r in results]), 2),
        mean_tool_success_rate=rounded(mean(tool_rates)),
        total_input_tokens=sum(r.input_tokens for r in results),
        total_output_tokens=sum(r.output_tokens for r in results),
        total_cost_usd=(
            round(sum(c for c in costs if c is not None), 6)
            if costs and all(c is not None for c in costs)
            else None
        ),
        errors=sum(1 for r in results if r.status != RunStatus.SUCCEEDED),
        tasks=tasks,
    )


class BenchmarkRecorder:
    """Persistence hooks used by the runner (implemented by the storage layer)."""

    async def save_benchmark(self, bench: BenchmarkRun) -> None:  # pragma: no cover
        return None

    def run_observers(self, bench: BenchmarkRun) -> list[RunObserver]:  # pragma: no cover
        return []


class BenchmarkRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        recorder: BenchmarkRecorder | None = None,
        memory: MemoryStore | None = None,
        concurrency: int = 1,
        env: dict[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.recorder = recorder or BenchmarkRecorder()
        self.memory = memory
        self.concurrency = max(1, concurrency)
        self.env = env

    async def run(
        self,
        suite: BenchmarkSuite,
        config: AgentConfig,
        *,
        repeats: int | None = None,
        task_ids: list[str] | None = None,
        experiment_id: str | None = None,
        variant: str | None = None,
        bench: BenchmarkRun | None = None,
    ) -> BenchmarkRun:
        tasks = [suite.task(t) for t in task_ids] if task_ids else list(suite.tasks)
        if not tasks:
            raise BenchmarkError("no tasks selected")
        repeats = repeats or suite.repeats
        bench = bench or BenchmarkRun(
            suite_id=suite.id,
            suite_name=suite.name,
            agent_name=config.name,
            agent_config=config,
            suite=suite,
            repeats=repeats,
            experiment_id=experiment_id,
            variant=variant,
            environment=environment_info(config),
        )
        bench.status = RunStatus.RUNNING
        await self.recorder.save_benchmark(bench)

        semaphore = asyncio.Semaphore(self.concurrency)
        lock = asyncio.Lock()

        async def one(task: BenchmarkTask, repeat: int) -> None:
            async with semaphore:
                result = await self._run_task(bench, suite, config, task, repeat)
            async with lock:
                bench.results.append(result)
                await self.recorder.save_benchmark(bench)

        try:
            await asyncio.gather(*(one(t, r) for r in range(1, repeats + 1) for t in tasks))
            bench.status = RunStatus.SUCCEEDED
        except asyncio.CancelledError:
            bench.status = RunStatus.CANCELLED
            raise
        except Exception:
            logger.exception("benchmark %s failed", bench.id)
            bench.status = RunStatus.FAILED
        finally:
            order = {t.id: i for i, t in enumerate(suite.tasks)}
            bench.results.sort(key=lambda r: (order.get(r.task_id, 0), r.repeat))
            bench.summary = summarize(bench.results, [t.id for t in tasks])
            bench.finished_at = utcnow()
            await asyncio.shield(self.recorder.save_benchmark(bench))
        return bench

    async def _run_task(
        self,
        bench: BenchmarkRun,
        suite: BenchmarkSuite,
        config: AgentConfig,
        task: BenchmarkTask,
        repeat: int,
    ) -> TaskRunResult:
        effective = task_config(config, suite, task)
        labels = {"benchmark": suite.id, "task": task.id, "repeat": str(repeat)}
        if bench.variant:
            labels["variant"] = bench.variant
        prepared = prepare_run(
            effective,
            task.goal,
            settings=self.settings,
            memory=self.memory,
            observers=self.recorder.run_observers(bench),
            initial_files=task.setup.files,
            env=self.env,
            labels=labels,
        )
        setup_error = await self._setup(prepared.runtime.deps.sandbox, task)
        if setup_error is not None:
            run = prepared.run
            run.status = RunStatus.FAILED
            await prepared.provider.aclose()
            await prepared.runtime.deps.sandbox.close()
            return TaskRunResult(
                task_id=task.id,
                repeat=repeat,
                run_id=run.id,
                status=RunStatus.FAILED,
                passed=False,
                score=0.0,
                error=f"task setup failed: {setup_error}",
            )
        run = await prepared.execute(task.evaluators)
        return result_from_run(task.id, repeat, run)

    @staticmethod
    async def _setup(sandbox: Any, task: BenchmarkTask) -> str | None:
        commands = list(task.setup.commands)
        if task.setup.git_init:
            commands += [
                "git init -q -b main",
                "git add -A",
                "git -c user.name=AgentForge -c user.email=setup@agentforge.invalid "
                "commit -q -m 'initial state' --allow-empty",
            ]
        if not commands:
            return None
        await sandbox.start()
        for command in commands:
            result = await sandbox.exec(["sh", "-c", command], timeout=300)
            if not result.ok:
                return f"`{command}` exited {result.exit_code}: {result.stderr.strip()[:300]}"
        return None
