"""Benchmark suites, benchmark runs and experiments."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from agentforge.api.deps import ServiceDep, audit, resolve_config
from agentforge.api.schemas import BenchmarkRunCreate, ExperimentCreate, SuiteInfo
from agentforge.benchmarks.report import BenchmarkReport, build_report
from agentforge.benchmarks.runner import BenchmarkRun, ResultClass
from agentforge.benchmarks.spec import BenchmarkSuite, discover_suites
from agentforge.experiments import Experiment, ExperimentSpec, compare
from agentforge.improvement import BenchmarkComparison, FailureAnalysis
from agentforge.storage import AgentRepository

router = APIRouter(tags=["benchmarks"])


def _suites(service: ServiceDep) -> dict[str, Any]:
    return discover_suites(service.settings.benchmark_dirs)


def _suite(service: ServiceDep, suite_id: str) -> tuple[str, BenchmarkSuite]:
    found = _suites(service).get(suite_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"benchmark suite '{suite_id}' not found")
    path, suite = found
    return str(path), suite


def _info(path: str, suite: BenchmarkSuite) -> SuiteInfo:
    return SuiteInfo(
        id=suite.id,
        name=suite.name,
        description=suite.description,
        version=suite.version,
        repeats=suite.repeats,
        path=path,
        tasks=[
            {
                "id": t.id,
                "goal": t.goal,
                "expected_behavior": t.expected_behavior,
                "allowed_tools": t.allowed_tools,
                "evaluators": [e.model_dump(mode="json") for e in t.evaluators],
                "tags": t.tags,
            }
            for t in suite.tasks
        ],
    )


@router.get("/benchmarks/suites", response_model=list[SuiteInfo])
async def list_suites(service: ServiceDep) -> list[SuiteInfo]:
    return [_info(str(path), suite) for path, suite in _suites(service).values()]


@router.get("/benchmarks/suites/{suite_id}", response_model=SuiteInfo)
async def get_suite(suite_id: str, service: ServiceDep) -> SuiteInfo:
    return _info(*_suite(service, suite_id))


@router.post("/benchmarks/runs", response_model=BenchmarkRun, status_code=status.HTTP_202_ACCEPTED)
async def start_benchmark(
    body: BenchmarkRunCreate, service: ServiceDep, request: Request
) -> BenchmarkRun:
    _, suite = _suite(service, body.suite_id)
    agent_id: str | None = None
    version: int | None = None
    if body.agent_id is not None:
        # One snapshot: the config that runs and the version recorded must match.
        agent = await AgentRepository(service.db).get(body.agent_id)
        config, agent_id, version = agent.config, agent.id, agent.version
    else:
        config, _ = await resolve_config(service, None, body.config)
    bench = await service.start_benchmark(
        suite,
        config,
        repeats=body.repeats,
        task_ids=body.task_ids,
        agent_id=agent_id,
        agent_version=version,
    )
    audit(request, "benchmark.start", benchmark_run_id=bench.id, suite=suite.id)
    return bench


@router.get("/benchmarks/runs", response_model=list[BenchmarkRun])
async def list_benchmark_runs(  # noqa: PLR0917 - FastAPI query parameters
    service: ServiceDep,
    suite_id: str | None = None,
    experiment_id: str | None = None,
    agent_id: str | None = None,
    result_class: ResultClass | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[BenchmarkRun]:
    return await service.recorder.benchmarks.list(
        suite_id=suite_id,
        experiment_id=experiment_id,
        agent_id=agent_id,
        result_class=result_class.value if result_class else None,
        limit=limit,
    )


@router.get("/benchmarks/runs/{bench_id}", response_model=BenchmarkRun)
async def get_benchmark_run(bench_id: str, service: ServiceDep) -> BenchmarkRun:
    return await service.recorder.benchmarks.get(bench_id)


@router.get("/benchmarks/runs/{bench_id}/analysis", response_model=FailureAnalysis)
async def analyze_benchmark_run(bench_id: str, service: ServiceDep) -> FailureAnalysis:
    """Failure categories and evidence for a benchmark run (derived from run records)."""
    return await service.improvements.analyze(bench_id)


@router.get("/benchmarks/runs/{bench_id}/report", response_model=BenchmarkReport)
async def benchmark_report(bench_id: str, service: ServiceDep) -> BenchmarkReport:
    """Publication record: per-run success, checks, tool calls, retries, tokens and cost."""
    bench = await service.recorder.benchmarks.get(bench_id)
    page = await service.runs.list(benchmark_run_id=bench.id, limit=len(bench.results) + 50)
    return build_report(bench, {run.id: run for run in page.items})


@router.get("/benchmarks/compare", response_model=BenchmarkComparison)
async def compare_benchmark_runs(
    baseline: str, candidate: str, service: ServiceDep
) -> BenchmarkComparison:
    """Compare two runs of the same suite. Offline and real results are never compared."""
    return await service.improvements.compare(baseline, candidate)


@router.post("/experiments", response_model=Experiment, status_code=status.HTTP_202_ACCEPTED)
async def start_experiment(
    body: ExperimentCreate, service: ServiceDep, request: Request
) -> Experiment:
    path, suite = _suite(service, body.suite_id)
    base, _ = await resolve_config(service, body.base_agent_id, body.base_config)
    spec = ExperimentSpec(
        name=body.name,
        description=body.description,
        benchmark=path,
        base_agent=base.model_dump(mode="json"),
        variants=body.variants,
        repeats=body.repeats,
        task_ids=body.task_ids,
    )
    experiment = await service.start_experiment(spec, suite, base)
    audit(request, "experiment.start", experiment_id=experiment.id, suite=suite.id)
    return experiment


@router.get("/experiments", response_model=list[Experiment])
async def list_experiments(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[Experiment]:
    return await service.recorder.experiments.list(limit=limit)


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str, service: ServiceDep) -> dict[str, Any]:
    experiment = await service.recorder.experiments.get(experiment_id)
    return {
        "experiment": experiment.model_dump(mode="json"),
        "comparison": [row.model_dump(mode="json") for row in compare(experiment)],
    }
