from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.benchmarks import BenchmarkRunner, BenchmarkSuite, load_suite, summarize
from agentforge.benchmarks.runner import TaskRunResult
from agentforge.benchmarks.stats import stddev, wilson_interval
from agentforge.config_files import load_agent_config
from agentforge.core.errors import BenchmarkError, ConfigurationError
from agentforge.core.models import RunStatus
from agentforge.experiments import (
    ExperimentRunner,
    Variant,
    compare,
    deep_merge,
    load_experiment,
    variant_config,
)
from agentforge.settings import Settings
from agentforge.storage import Database, RunRepository
from agentforge.storage.tracking import StorageRecorder

pytestmark = pytest.mark.integration

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_example_suite_loads() -> None:
    suite = load_suite(EXAMPLES / "benchmarks" / "starter.yaml")
    assert suite.id == "starter"
    assert {t.id for t in suite.tasks} == {
        "create-greeting",
        "fix-failing-test",
        "count-csv-rows",
        "git-feature-branch",
    }


def test_suite_validation_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: x\nname: x\ntasks:\n  - {id: a, goal: g, evaluators: []}\n")
    with pytest.raises(BenchmarkError):
        load_suite(bad)
    dup = {
        "id": "x",
        "name": "x",
        "tasks": [
            {"id": "a", "goal": "g", "evaluators": [{"type": "completed"}]},
            {"id": "a", "goal": "g", "evaluators": [{"type": "completed"}]},
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        BenchmarkSuite.model_validate(dup)


def test_statistics() -> None:
    low, high = wilson_interval(8, 10) or (0, 0)
    assert 0.49 < low < 0.5 and 0.94 < high < 0.95
    assert wilson_interval(0, 0) is None
    assert wilson_interval(0, 5) is not None
    assert stddev([1.0]) is None
    assert stddev([1.0, 3.0]) == pytest.approx(1.4142, rel=1e-3)


def test_summarize_cost_unknown_if_any_unknown() -> None:
    def result(task: str, passed: bool, cost: float | None) -> TaskRunResult:
        return TaskRunResult(
            task_id=task,
            repeat=1,
            run_id="r",
            status=RunStatus.SUCCEEDED,
            passed=passed,
            score=float(passed),
            cost_usd=cost,
        )

    summary = summarize([result("a", True, 0.1), result("b", False, None)], ["a", "b"])
    assert summary.pass_rate == 0.5 and summary.total_cost_usd is None
    assert [t.task_id for t in summary.tasks] == ["a", "b"]
    assert summarize([result("a", True, 0.1), result("a", True, 0.2)], ["a"]).total_cost_usd == 0.3


async def test_scripted_agent_solves_starter_suite(settings: Settings, db: Database) -> None:
    suite = load_suite(EXAMPLES / "benchmarks" / "starter.yaml")
    config = load_agent_config(EXAMPLES / "agents" / "scripted-demo.yaml")
    recorder = StorageRecorder(db)
    bench = await BenchmarkRunner(settings, recorder=recorder, concurrency=2).run(
        suite, config, repeats=2
    )
    assert bench.status == RunStatus.SUCCEEDED
    assert bench.summary is not None
    assert bench.summary.runs == 8
    failures = [(r.task_id, r.error) for r in bench.results if not r.passed]
    assert bench.summary.pass_rate == 1.0, failures
    assert [r.task_id for r in bench.results][:2] == ["create-greeting", "create-greeting"]

    stored = await recorder.benchmarks.get(bench.id)
    assert stored.summary == bench.summary
    runs = await RunRepository(db).list(benchmark_run_id=bench.id)
    assert runs.total == 8
    assert all(r.labels["benchmark"] == "starter" for r in runs.items)


async def test_task_allowed_tools_restrict_agent(settings: Settings) -> None:
    suite = BenchmarkSuite.model_validate(
        {
            "id": "restrict",
            "name": "r",
            "tasks": [
                {
                    "id": "t",
                    "goal": "run something",
                    "allowed_tools": ["filesystem"],
                    "evaluators": [{"type": "tool_used", "tool": "run_command"}],
                }
            ],
        }
    )
    config = load_agent_config(EXAMPLES / "agents" / "scripted-demo.yaml").model_copy(
        update={
            "model": load_agent_config(EXAMPLES / "agents" / "scripted-demo.yaml").model.model_copy(
                update={
                    "options": {
                        "turns": [
                            {
                                "tool_calls": [
                                    {"name": "run_command", "arguments": {"command": "true"}}
                                ]
                            },
                            {"text": "done"},
                        ]
                    }
                }
            )
        }
    )
    bench = await BenchmarkRunner(settings).run(suite, config)
    assert not bench.results[0].passed  # run_command was not available to the agent


async def test_setup_failure_is_recorded(settings: Settings) -> None:
    suite = BenchmarkSuite.model_validate(
        {
            "id": "setup",
            "name": "s",
            "tasks": [
                {
                    "id": "t",
                    "goal": "g",
                    "setup": {"commands": ["exit 7"]},
                    "evaluators": [{"type": "completed"}],
                }
            ],
        }
    )
    config = load_agent_config(EXAMPLES / "agents" / "scripted-demo.yaml")
    bench = await BenchmarkRunner(settings).run(suite, config)
    assert bench.results[0].status == RunStatus.FAILED
    assert "setup failed" in (bench.results[0].error or "")


def test_deep_merge_and_variant_validation() -> None:
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {"a": {"b": 3, "c": 2}}
    base = load_agent_config(EXAMPLES / "agents" / "scripted-demo.yaml")
    merged = variant_config(base, Variant(name="v", overrides={"limits": {"max_steps": 3}}))
    assert (
        merged.limits.max_steps == 3
        and merged.limits.timeout_seconds == base.limits.timeout_seconds
    )
    with pytest.raises(ConfigurationError):
        variant_config(base, Variant(name="bad", overrides={"limits": {"max_steps": 0}}))


async def test_experiment_compares_variants(settings: Settings, db: Database) -> None:
    spec, suite, base = load_experiment(EXAMPLES / "experiments" / "step-budget.yaml")
    recorder = StorageRecorder(db)
    experiment = await ExperimentRunner(BenchmarkRunner(settings, recorder=recorder), recorder).run(
        spec, suite, base
    )
    assert experiment.status == RunStatus.SUCCEEDED
    rows = {r.variant: r for r in compare(experiment)}
    assert rows["baseline"].pass_rate == 1.0
    assert rows["max-steps-2"].task_pass_rates["fix-failing-test"] == 0.0
    assert (
        rows["max-steps-2"].pass_rate_delta is not None and rows["max-steps-2"].pass_rate_delta < 0
    )
    stored = await recorder.experiments.get(experiment.id)
    assert [v.variant for v in stored.variants] == ["baseline", "max-steps-2"]
    benches = await recorder.benchmarks.list(experiment_id=experiment.id)
    assert len(benches) == 2
