"""Experiments: compare agent configuration variants on the same benchmark.

An experiment runs one benchmark suite once per *variant* (a set of overrides
deep-merged into a base agent config: model, prompt, tools, planner, ...) and
reports per-variant aggregates plus per-task pass rates side by side.

Results describe *these* configurations on *this* suite with the stated number
of runs; they are not general model rankings. Confidence intervals are shown so
small differences are not over-interpreted.
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentforge.benchmarks.runner import BenchmarkRun, BenchmarkRunner, BenchmarkSummary
from agentforge.benchmarks.spec import BenchmarkSuite, load_suite
from agentforge.core.config import AgentConfig
from agentforge.core.errors import BenchmarkError, ConfigurationError
from agentforge.core.ids import new_id, utcnow
from agentforge.core.models import RunStatus


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    benchmark: str = Field(description="Path to the suite file (relative to the spec file).")
    base_agent: dict[str, Any] | str = Field(
        description="Inline agent config or path to an agent YAML file."
    )
    variants: list[Variant] = Field(min_length=1)
    repeats: int | None = Field(default=None, ge=1, le=100)
    task_ids: list[str] | None = None

    @model_validator(mode="after")
    def _unique_variants(self) -> ExperimentSpec:
        names = [v.name for v in self.variants]
        if len(set(names)) != len(names):
            raise ValueError("variant names must be unique")
        return self


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def variant_config(base: AgentConfig, variant: Variant) -> AgentConfig:
    data = deep_merge(base.model_dump(mode="json"), variant.overrides)
    try:
        return AgentConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigurationError(
            f"variant '{variant.name}' produces an invalid config: {exc}"
        ) from exc


class VariantResult(BaseModel):
    variant: str
    benchmark_run_id: str
    provider: str
    model: str
    summary: BenchmarkSummary | None = None
    status: RunStatus = RunStatus.PENDING


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exp"))
    name: str
    description: str = ""
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    spec: ExperimentSpec
    suite_id: str = ""
    variants: list[VariantResult] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    variant: str
    runs: int
    pass_rate: float
    pass_rate_ci95: tuple[float, float] | None
    mean_score: float
    mean_duration_seconds: float | None
    mean_steps: float | None
    total_cost_usd: float | None
    pass_rate_delta: float | None = Field(
        default=None, description="Difference from the first (baseline) variant."
    )
    task_pass_rates: dict[str, float] = Field(default_factory=dict)


def compare(experiment: Experiment) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    baseline: float | None = None
    for result in experiment.variants:
        s = result.summary
        if s is None:
            continue
        if baseline is None:
            baseline = s.pass_rate
        rows.append(
            ComparisonRow(
                variant=result.variant,
                runs=s.runs,
                pass_rate=s.pass_rate,
                pass_rate_ci95=s.pass_rate_ci95,
                mean_score=s.mean_score,
                mean_duration_seconds=s.mean_duration_seconds,
                mean_steps=s.mean_steps,
                total_cost_usd=s.total_cost_usd,
                pass_rate_delta=round(s.pass_rate - baseline, 4),
                task_pass_rates={t.task_id: t.pass_rate for t in s.tasks},
            )
        )
    return rows


def load_experiment(path: str | Path) -> tuple[ExperimentSpec, BenchmarkSuite, AgentConfig]:
    """Load a spec file and resolve its benchmark and base agent (paths are relative)."""
    path = Path(path)
    try:
        spec = ExperimentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise BenchmarkError(f"invalid experiment spec {path}: {exc}") from exc
    suite = load_suite(path.parent / spec.benchmark)
    if isinstance(spec.base_agent, str):
        from agentforge.config_files import load_agent_config

        base = load_agent_config(path.parent / spec.base_agent)
    else:
        base = AgentConfig.model_validate(spec.base_agent)
    return spec, suite, base


class ExperimentRecorder:
    async def save_experiment(self, experiment: Experiment) -> None:  # pragma: no cover
        return None


class ExperimentRunner:
    def __init__(
        self, benchmark_runner: BenchmarkRunner, recorder: ExperimentRecorder | None = None
    ) -> None:
        self.benchmarks = benchmark_runner
        self.recorder = recorder or ExperimentRecorder()

    async def run(
        self,
        spec: ExperimentSpec,
        suite: BenchmarkSuite,
        base: AgentConfig,
        *,
        experiment: Experiment | None = None,
    ) -> Experiment:
        configs = [(v, variant_config(base, v)) for v in spec.variants]  # validate all first
        experiment = experiment or Experiment(
            name=spec.name, description=spec.description, spec=spec, suite_id=suite.id
        )
        experiment.suite_id = suite.id
        experiment.status = RunStatus.RUNNING
        await self.recorder.save_experiment(experiment)
        try:
            for variant, config in configs:
                bench = BenchmarkRun(
                    suite_id=suite.id,
                    suite_name=suite.name,
                    agent_name=config.name,
                    agent_config=config,
                    suite=suite,
                    repeats=spec.repeats or suite.repeats,
                    experiment_id=experiment.id,
                    variant=variant.name,
                )
                entry = VariantResult(
                    variant=variant.name,
                    benchmark_run_id=bench.id,
                    provider=config.model.provider,
                    model=config.model.model,
                    status=RunStatus.RUNNING,
                )
                experiment.variants.append(entry)
                await self.recorder.save_experiment(experiment)
                result: BenchmarkRun = await self.benchmarks.run(
                    suite,
                    config,
                    repeats=spec.repeats,
                    task_ids=spec.task_ids,
                    experiment_id=experiment.id,
                    variant=variant.name,
                    bench=bench,
                )
                entry.summary = result.summary
                entry.status = result.status
                await self.recorder.save_experiment(experiment)
            experiment.status = RunStatus.SUCCEEDED
        except BaseException:
            experiment.status = RunStatus.FAILED
            raise
        finally:
            experiment.finished_at = utcnow()
            await self.recorder.save_experiment(experiment)
        return experiment


__all__ = [
    "ComparisonRow",
    "Experiment",
    "ExperimentRunner",
    "ExperimentSpec",
    "Variant",
    "VariantResult",
    "compare",
    "deep_merge",
    "load_experiment",
    "variant_config",
]
