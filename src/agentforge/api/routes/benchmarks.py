"""Benchmark suites, benchmark runs and experiments."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from agentforge.api.deps import ServiceDep, resolve_config
from agentforge.api.schemas import BenchmarkRunCreate, ExperimentCreate, SuiteInfo
from agentforge.benchmarks.runner import BenchmarkRun
from agentforge.benchmarks.spec import BenchmarkSuite, discover_suites
from agentforge.experiments import Experiment, ExperimentSpec, compare

router = APIRouter(tags=["benchmarks"])


def _suites(service: ServiceDep) -> dict[str, Any]:
    return discover_suites(service.settings.benchmarks_dir)


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
async def start_benchmark(body: BenchmarkRunCreate, service: ServiceDep) -> BenchmarkRun:
    _, suite = _suite(service, body.suite_id)
    config, _ = await resolve_config(service, body.agent_id, body.config)
    return await service.start_benchmark(
        suite, config, repeats=body.repeats, task_ids=body.task_ids
    )


@router.get("/benchmarks/runs", response_model=list[BenchmarkRun])
async def list_benchmark_runs(
    service: ServiceDep,
    suite_id: str | None = None,
    experiment_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[BenchmarkRun]:
    return await service.recorder.benchmarks.list(
        suite_id=suite_id, experiment_id=experiment_id, limit=limit
    )


@router.get("/benchmarks/runs/{bench_id}", response_model=BenchmarkRun)
async def get_benchmark_run(bench_id: str, service: ServiceDep) -> BenchmarkRun:
    return await service.recorder.benchmarks.get(bench_id)


@router.post("/experiments", response_model=Experiment, status_code=status.HTTP_202_ACCEPTED)
async def start_experiment(body: ExperimentCreate, service: ServiceDep) -> Experiment:
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
    return await service.start_experiment(spec, suite, base)


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
