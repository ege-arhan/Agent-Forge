from __future__ import annotations

from datetime import timedelta

import pytest

from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.core.errors import ConfigurationError
from agentforge.core.ids import utcnow
from agentforge.core.models import (
    EvaluatorResult,
    LLMCallRecord,
    Run,
    RunStatus,
    Step,
    StepKind,
    ToolCallRecord,
    ToolCallStatus,
)
from agentforge.evaluation import (
    EvaluationContext,
    Evaluator,
    EvaluatorSpec,
    Verdict,
    aggregate,
    available_evaluators,
    compute_metrics,
    evaluate,
)
from agentforge.llm.registry import register_provider
from agentforge.llm.scripted import ScriptedProvider
from agentforge.sandbox.local import LocalSandbox
from agentforge.sandbox.workspace import Workspace


def make_run(
    result: str | None = "The answer is 42", status: RunStatus = RunStatus.SUCCEEDED
) -> Run:
    return Run(
        agent_name="a",
        config=AgentConfig(name="a", model=ModelConfig(provider="scripted")),
        goal="compute the answer",
        status=status,
        result=result,
    )


def ctx(run: Run, workspace: Workspace) -> EvaluationContext:
    return EvaluationContext(run=run, workspace=workspace, sandbox=LocalSandbox(workspace))


def test_builtin_evaluators_registered() -> None:
    names = set(available_evaluators())
    assert {
        "completed",
        "output_contains",
        "output_matches",
        "file_exists",
        "file_contains",
        "command",
        "max_steps",
        "tool_used",
        "llm_judge",
    } <= names


async def test_output_evaluators(workspace: Workspace) -> None:
    run = make_run()
    result = await evaluate(
        [
            EvaluatorSpec(type="output_contains", text=["answer", "42"]),
            EvaluatorSpec(type="output_contains", text=["43", "42"], name="partial"),
            EvaluatorSpec(type="output_matches", pattern=r"\b42\b"),
            EvaluatorSpec(type="completed"),
        ],
        ctx(run, workspace),
    )
    assert result is not None
    by_name = {r.name: r for r in result.results}
    assert by_name["output_contains"].passed
    assert not by_name["partial"].passed and by_name["partial"].score == 0.5
    assert by_name["output_matches"].passed
    assert not result.passed
    assert result.score == pytest.approx((1 + 0.5 + 1 + 1) / 4)


async def test_file_and_command_evaluators(workspace: Workspace) -> None:
    (workspace.root / "report.md").write_text("# Report\nstatus: OK\n")
    result = await evaluate(
        [
            EvaluatorSpec(type="file_exists", path="report.md"),
            EvaluatorSpec(type="file_contains", path="report.md", pattern=r"status:\s+OK"),
            EvaluatorSpec(type="file_contains", path="report.md", text="missing", required=False),
            EvaluatorSpec(type="command", command="grep -q OK report.md"),
        ],
        ctx(make_run(), workspace),
    )
    assert result is not None
    assert result.passed  # the failing check is not required
    assert [r.passed for r in result.results] == [True, True, False, True]
    assert result.results[3].metrics["exit_code"] == 0


async def test_command_evaluator_failure_includes_output(workspace: Workspace) -> None:
    result = await evaluate(
        [EvaluatorSpec(type="command", command="echo boom; exit 2")], ctx(make_run(), workspace)
    )
    assert result is not None and not result.passed
    assert "exit code 2" in result.results[0].details and "boom" in result.results[0].details


async def test_evaluator_errors_are_recorded(workspace: Workspace) -> None:
    result = await evaluate(
        [EvaluatorSpec(type="file_exists", path="../../etc/passwd")], ctx(make_run(), workspace)
    )
    assert result is not None and not result.passed
    assert "evaluator error" in result.results[0].details


async def test_unknown_evaluator_and_bad_params(workspace: Workspace) -> None:
    with pytest.raises(ConfigurationError):
        await evaluate([EvaluatorSpec(type="nope")], ctx(make_run(), workspace))
    with pytest.raises(ConfigurationError):
        await evaluate([EvaluatorSpec(type="file_exists", bogus=1)], ctx(make_run(), workspace))


class AlwaysHalf(Evaluator):
    type_name = "always_half"

    async def check(self, ctx: EvaluationContext) -> Verdict:
        return Verdict(passed=True, score=0.5)


async def test_python_custom_evaluator(workspace: Workspace) -> None:
    spec = EvaluatorSpec(type="python", **{"class": f"{__name__}:AlwaysHalf"})
    result = await evaluate([spec], ctx(make_run(), workspace))
    assert result is not None and result.score == 0.5


async def test_llm_judge_uses_configured_model(workspace: Workspace) -> None:
    register_provider(
        "judge-test",
        lambda config, env: ScriptedProvider.from_options(
            {"turns": [{"text": 'Sure: {"score": 0.8, "reason": "mostly right"}'}]}
        ),
    )
    spec = EvaluatorSpec(type="llm_judge", rubric="Is it 42?", model={"provider": "judge-test"})
    result = await evaluate([spec], ctx(make_run(), workspace))
    assert result is not None
    assert result.results[0].score == 0.8 and result.passed
    assert result.results[0].details == "mostly right"


async def test_llm_judge_unparseable(workspace: Workspace) -> None:
    register_provider(
        "judge-bad",
        lambda config, env: ScriptedProvider.from_options({"turns": [{"text": "no idea"}]}),
    )
    spec = EvaluatorSpec(type="llm_judge", rubric="x", model={"provider": "judge-bad"})
    result = await evaluate([spec], ctx(make_run(), workspace))
    assert result is not None and not result.passed


def test_aggregate_weights_and_required() -> None:
    result = aggregate(
        [
            EvaluatorResult(name="a", passed=True, score=1.0, weight=3),
            EvaluatorResult(name="b", passed=False, score=0.0, weight=1, required=False),
        ]
    )
    assert result.passed and result.score == 0.75
    assert "b" in result.feedback()


def test_evaluate_empty_returns_none(workspace: Workspace) -> None:
    import asyncio

    assert asyncio.run(evaluate([], ctx(make_run(), workspace))) is None


def test_compute_metrics_from_records() -> None:
    now = utcnow()
    run = make_run()
    run.started_at, run.finished_at = now, now + timedelta(seconds=2.5)

    def llm(attempts: int, cost: float | None) -> LLMCallRecord:
        return LLMCallRecord(
            provider="p",
            model="m",
            started_at=now,
            finished_at=now,
            latency_ms=5,
            attempts=attempts,
            cost_usd=cost,
        )

    def tool(status: ToolCallStatus) -> ToolCallRecord:
        return ToolCallRecord(
            id="c", tool="t", status=status, started_at=now, finished_at=now, duration_ms=1
        )

    run.steps = [
        Step(
            index=0,
            kind=StepKind.ACTION,
            llm_call=llm(2, 0.01),
            tool_calls=[tool(ToolCallStatus.SUCCESS), tool(ToolCallStatus.ERROR)],
        ),
        Step(index=1, kind=StepKind.ACTION, llm_call=llm(1, 0.02)),
        Step(index=2, kind=StepKind.EVALUATION),
    ]
    metrics = compute_metrics(run)
    assert metrics.duration_seconds == 2.5
    assert (metrics.steps, metrics.llm_calls, metrics.llm_retries) == (2, 2, 1)
    assert (metrics.tool_calls, metrics.tool_errors, metrics.tool_success_rate) == (2, 1, 0.5)
    assert metrics.cost_usd == pytest.approx(0.03)

    run.steps[1].llm_call = llm(1, None)
    assert compute_metrics(run).cost_usd is None  # never report partial cost as total
