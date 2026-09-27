"""Benchmark result reports for publication (e.g. the dogfooding program).

A report records, per task run: model, provider, benchmark version, task,
success, the individual test/evaluator results, tool calls, duration, retry
counts, token usage and cost. Values that were not measured are ``None`` -
never zero and never estimated:

- token counts are ``None`` when the provider reported no usage (the scripted
  provider never does);
- ``actual_cost_usd`` is always ``None``: AgentForge does not read provider
  billing. ``estimated_cost_usd`` comes from the pricing table and is ``None``
  when pricing is unknown.

Reports are written under ``<root>/<result_class>/...``, so offline (scripted)
and real-model results can never end up in the same place.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agentforge import __version__
from agentforge.benchmarks.runner import BenchmarkRun, ResultClass
from agentforge.benchmarks.stats import mean, rounded, wilson_interval
from agentforge.core.models import Run

REPORT_SCHEMA_VERSION = 1


class CheckResult(BaseModel):
    name: str
    passed: bool
    score: float
    required: bool
    details: str = ""


class TaskRunRecord(BaseModel):
    task_id: str
    repeat: int
    run_id: str
    status: str
    success: bool
    score: float
    checks: list[CheckResult] = Field(default_factory=list, description="Evaluator results.")
    steps: int | None = None
    tool_calls: int | None = None
    tool_errors: int | None = None
    duration_seconds: float | None = None
    llm_retries: int | None = None
    evaluation_retries: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    error: str | None = None
    failure_category: str | None = Field(
        default=None,
        description="Primary failure category of a failed run (failure analysis); null when "
        "the run passed or the report predates this field.",
    )


class ReportSummary(BaseModel):
    runs: int
    passed: int
    pass_rate: float
    pass_rate_ci95: tuple[float, float] | None = None
    mean_duration_seconds: float | None = None
    total_tool_calls: int = 0
    total_llm_retries: int = 0
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None


class BenchmarkReport(BaseModel):
    schema_version: int = REPORT_SCHEMA_VERSION
    result_class: ResultClass
    benchmark_run_id: str
    status: str
    suite_id: str
    suite_name: str
    suite_version: str
    agent_name: str
    agent_id: str | None = None
    agent_version: int | None = None
    provider: str
    model: str
    agentforge_version: str
    environment: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    finished_at: datetime | None = None
    repeats: int
    suite_digest: str | None = Field(
        default=None,
        description="sha256 of the suite snapshot the runs used; null in reports that predate it.",
    )
    summary: ReportSummary
    runs: list[TaskRunRecord] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _usage_reported(run: Run) -> bool:
    return any(
        s.llm_call is not None and (s.llm_call.usage.input_tokens or s.llm_call.usage.output_tokens)
        for s in run.steps
    )


def _record(
    task_id: str, repeat: int, run_id: str, run: Run | None, error: str | None
) -> TaskRunRecord:
    if run is None:
        return TaskRunRecord(
            task_id=task_id,
            repeat=repeat,
            run_id=run_id,
            status="missing",
            success=False,
            score=0.0,
            error=error,
            failure_category="missing_record",
        )
    m = run.metrics
    usage = _usage_reported(run)
    evaluation = run.evaluation
    return TaskRunRecord(
        task_id=task_id,
        repeat=repeat,
        run_id=run.id,
        status=run.status.value,
        success=bool(evaluation and evaluation.passed),
        score=evaluation.score if evaluation else 0.0,
        checks=[
            CheckResult(
                name=r.name, passed=r.passed, score=r.score, required=r.required, details=r.details
            )
            for r in (evaluation.results if evaluation else [])
        ],
        steps=m.steps,
        tool_calls=m.tool_calls,
        tool_errors=m.tool_errors,
        duration_seconds=m.duration_seconds,
        llm_retries=m.llm_retries,
        evaluation_retries=m.evaluation_retries,
        input_tokens=m.input_tokens if usage else None,
        output_tokens=m.output_tokens if usage else None,
        estimated_cost_usd=m.cost_usd if usage else None,
        actual_cost_usd=None,
        error=f"{run.error.type}: {run.error.message}" if run.error else None,
        failure_category=_failure_category(run, evaluation is not None and evaluation.passed),
    )


def _failure_category(run: Run, passed: bool) -> str | None:
    """The failure analysis' primary category for a failed run (None when it passed)."""
    if passed:
        return None
    from agentforge.improvement.analysis import classify_run  # avoid an import cycle

    failure = classify_run(run)
    return failure.category.value if failure is not None else None


def suite_digest(bench: BenchmarkRun) -> str:
    """Stable hash of the suite snapshot: equal digests mean identical task definitions."""
    canonical = json.dumps(bench.suite.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sum(values: list[int | None]) -> int | None:
    return sum(v for v in values if v is not None) if values and None not in values else None


def build_report(bench: BenchmarkRun, runs: dict[str, Run]) -> BenchmarkReport:
    records = [
        _record(r.task_id, r.repeat, r.run_id, runs.get(r.run_id), r.error) for r in bench.results
    ]
    passed = sum(1 for r in records if r.success)
    ci = wilson_interval(passed, len(records))
    costs = [r.estimated_cost_usd for r in records]
    notes = [
        "Values that were not measured are null. actual_cost_usd is always null: AgentForge "
        "does not read provider billing; estimated_cost_usd uses the pricing table."
    ]
    if bench.result_class == ResultClass.OFFLINE:
        notes.append(
            "OFFLINE result: produced by the deterministic scripted provider. It validates the "
            "pipeline and the benchmark tasks; it says nothing about any model's capability."
        )
    if any(r.input_tokens is None for r in records if r.status != "missing"):
        notes.append("Token usage was not reported by the provider for some or all runs.")
    return BenchmarkReport(
        result_class=bench.result_class,
        benchmark_run_id=bench.id,
        status=bench.status.value,
        suite_id=bench.suite_id,
        suite_name=bench.suite_name,
        suite_version=bench.suite.version,
        agent_name=bench.agent_name,
        agent_id=bench.agent_id,
        agent_version=bench.agent_version,
        provider=bench.agent_config.model.provider,
        model=bench.agent_config.model.model,
        agentforge_version=str(bench.environment.get("agentforge_version", __version__)),
        environment={k: v for k, v in bench.environment.items() if k != "platform"},
        created_at=bench.created_at,
        finished_at=bench.finished_at,
        repeats=bench.repeats,
        suite_digest=suite_digest(bench),
        summary=ReportSummary(
            runs=len(records),
            passed=passed,
            pass_rate=round(passed / len(records), 4) if records else 0.0,
            pass_rate_ci95=(round(ci[0], 4), round(ci[1], 4)) if ci else None,
            mean_duration_seconds=rounded(
                mean([r.duration_seconds for r in records if r.duration_seconds is not None]), 3
            ),
            total_tool_calls=sum(r.tool_calls or 0 for r in records),
            total_llm_retries=sum(r.llm_retries or 0 for r in records),
            total_input_tokens=_sum([r.input_tokens for r in records]),
            total_output_tokens=_sum([r.output_tokens for r in records]),
            estimated_cost_usd=(
                round(sum(c for c in costs if c is not None), 6)
                if costs and None not in costs
                else None
            ),
            actual_cost_usd=None,
        ),
        runs=records,
        notes=notes,
    )


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def render_markdown(report: BenchmarkReport) -> str:
    s = report.summary
    ci = f"{s.pass_rate_ci95[0]:.2f}-{s.pass_rate_ci95[1]:.2f}" if s.pass_rate_ci95 else "n/a"
    label = (
        "OFFLINE / SCRIPTED PROVIDER"
        if report.result_class == ResultClass.OFFLINE
        else ("REAL MODEL PROVIDER")
    )
    lines = [
        f"# {report.suite_name} — {label}",
        "",
        f"- Benchmark run: `{report.benchmark_run_id}` ({report.status})",
        f"- Suite: `{report.suite_id}` version {report.suite_version}",
        f"- Agent: `{report.agent_name}`"
        + (f" v{report.agent_version}" if report.agent_version is not None else ""),
        f"- Provider / model: `{report.provider}` / `{report.model or '-'}`",
        f"- AgentForge: {report.agentforge_version}",
        f"- Date: {report.created_at:%Y-%m-%d %H:%M} UTC, repeats: {report.repeats}",
        f"- Pass rate: {s.passed}/{s.runs} ({s.pass_rate:.0%}, 95% CI {ci})",
        f"- Tokens in/out: {_fmt(s.total_input_tokens)} / {_fmt(s.total_output_tokens)}; "
        f"estimated cost: {_fmt(s.estimated_cost_usd)}; actual cost: {_fmt(s.actual_cost_usd)}",
        "",
        "| task | repeat | success | checks passed | tool calls | retries | duration (s) "
        "| tokens in/out |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report.runs:
        checks = f"{sum(c.passed for c in r.checks)}/{len(r.checks)}"
        retries = None if r.llm_retries is None else r.llm_retries + (r.evaluation_retries or 0)
        lines.append(
            f"| {r.task_id} | {r.repeat} | {'yes' if r.success else 'no'} | {checks} "
            f"| {_fmt(r.tool_calls)} | {_fmt(retries)} | {_fmt(r.duration_seconds)} "
            f"| {_fmt(r.input_tokens)} / {_fmt(r.output_tokens)} |"
        )
    failed = [r for r in report.runs if not r.success]
    if failed:
        lines += ["", "## Failures", ""]
        for r in failed:
            first = next((c for c in r.checks if not c.passed), None)
            reason = r.error or (f"{first.name}: {first.details}" if first else "failed")
            lines.append(f"- `{r.task_id}` #{r.repeat}: {reason.splitlines()[0][:200]}")
    lines += ["", "## Notes", "", *[f"- {n}" for n in report.notes], ""]
    return "\n".join(lines)


def report_path(root: Path, report: BenchmarkReport) -> Path:
    """``<root>/<offline|real>/<suite>-v<version>/<timestamp>-<agent>-<id>.json``."""
    folder = root / report.result_class.value / f"{report.suite_id}-v{report.suite_version}"
    stamp = report.created_at.strftime("%Y%m%dT%H%M%SZ")
    return folder / f"{stamp}-{report.agent_name}-{report.benchmark_run_id}.json"


def save_report(root: Path, report: BenchmarkReport) -> Path:
    """Write the JSON report and a Markdown rendering next to it; returns the JSON path."""
    path = report_path(root, report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return path
