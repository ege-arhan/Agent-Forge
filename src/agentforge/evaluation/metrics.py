"""Objective run metrics, computed only from recorded data."""

from __future__ import annotations

from agentforge.core.models import Run, RunMetrics, StepKind, ToolCallStatus


def compute_metrics(run: Run) -> RunMetrics:
    duration = None
    if run.started_at and run.finished_at:
        duration = round((run.finished_at - run.started_at).total_seconds(), 3)

    llm_calls = [s.llm_call for s in run.steps if s.llm_call is not None]
    tool_calls = run.tool_calls
    tool_errors = sum(1 for c in tool_calls if c.status != ToolCallStatus.SUCCESS)

    cost: float | None = None
    if llm_calls and all(c.cost_usd is not None for c in llm_calls):
        cost = round(sum(c.cost_usd or 0.0 for c in llm_calls), 6)

    errors = sum(1 for s in run.steps if s.error is not None) + (1 if run.error else 0)
    return RunMetrics(
        duration_seconds=duration,
        steps=sum(1 for s in run.steps if s.kind == StepKind.ACTION),
        llm_calls=len(llm_calls),
        llm_retries=sum(max(0, c.attempts - 1) for c in llm_calls),
        evaluation_retries=max(0, sum(1 for s in run.steps if s.kind == StepKind.EVALUATION) - 1),
        tool_calls=len(tool_calls),
        tool_errors=tool_errors,
        tool_success_rate=(
            round((len(tool_calls) - tool_errors) / len(tool_calls), 4) if tool_calls else None
        ),
        errors=errors,
        input_tokens=run.usage.input_tokens,
        output_tokens=run.usage.output_tokens,
        cost_usd=cost,
    )
