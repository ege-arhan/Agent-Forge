"""Compare two benchmark runs of the same suite (e.g. agent version N vs N+1)."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, Field

from agentforge.benchmarks.runner import BenchmarkRun, ResultClass, TaskRunResult
from agentforge.benchmarks.stats import mean, rounded, wilson_interval
from agentforge.improvement.analysis import FailureAnalysis


class Verdict(StrEnum):
    IMPROVED = "improved"  # higher pass rate, 95% intervals do not overlap
    REGRESSED = "regressed"  # lower pass rate, 95% intervals do not overlap
    UNCHANGED = "unchanged"  # same results on every task
    INCONCLUSIVE = "inconclusive"  # a difference the sample cannot establish
    NOT_COMPARABLE = "not_comparable"


class TaskChange(StrEnum):
    FIXED = "fixed"  # never passed -> always passed
    BROKEN = "broken"  # always passed -> never passed
    BETTER = "better"
    WORSE = "worse"
    UNCHANGED = "unchanged"


class SideSummary(BaseModel):
    benchmark_run_id: str
    agent_name: str
    agent_version: int | None = None
    provider: str
    model: str
    runs: int
    passed: int
    pass_rate: float
    pass_rate_ci95: tuple[float, float] | None = None
    mean_score: float
    mean_steps: float | None = None
    mean_duration_seconds: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float | None = None


class TaskDelta(BaseModel):
    task_id: str
    baseline_passed: int
    baseline_runs: int
    candidate_passed: int
    candidate_runs: int
    pass_rate_delta: float
    change: TaskChange


class CategoryDelta(BaseModel):
    category: str
    baseline: int
    candidate: int


class BenchmarkComparison(BaseModel):
    baseline_id: str
    candidate_id: str
    suite_id: str
    suite_version: str
    result_class: ResultClass
    comparable: bool
    reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    baseline: SideSummary | None = None
    candidate: SideSummary | None = None
    pass_rate_delta: float | None = None
    mean_score_delta: float | None = None
    mean_steps_delta: float | None = None
    significant: bool = False
    verdict: Verdict
    tasks: list[TaskDelta] = Field(default_factory=list)
    categories: list[CategoryDelta] = Field(default_factory=list)


def _side(bench: BenchmarkRun, results: list[TaskRunResult]) -> SideSummary:
    passed = sum(1 for r in results if r.passed)
    ci = wilson_interval(passed, len(results))
    durations = [r.duration_seconds for r in results if r.duration_seconds is not None]
    costs = [r.cost_usd for r in results]
    return SideSummary(
        benchmark_run_id=bench.id,
        agent_name=bench.agent_name,
        agent_version=bench.agent_version,
        provider=bench.agent_config.model.provider,
        model=bench.agent_config.model.model,
        runs=len(results),
        passed=passed,
        pass_rate=round(passed / len(results), 4) if results else 0.0,
        pass_rate_ci95=(round(ci[0], 4), round(ci[1], 4)) if ci else None,
        mean_score=round(mean([r.score for r in results]) or 0.0, 4),
        mean_steps=rounded(mean([float(r.steps) for r in results]), 2),
        mean_duration_seconds=rounded(mean(durations), 3),
        total_input_tokens=sum(r.input_tokens for r in results),
        total_output_tokens=sum(r.output_tokens for r in results),
        total_cost_usd=(
            round(sum(c for c in costs if c is not None), 6)
            if costs and all(c is not None for c in costs)
            else None
        ),
    )


def _task_change(base_rate: float, cand_rate: float) -> TaskChange:
    if base_rate == 0.0 and cand_rate == 1.0:
        return TaskChange.FIXED
    if base_rate == 1.0 and cand_rate == 0.0:
        return TaskChange.BROKEN
    if cand_rate > base_rate:
        return TaskChange.BETTER
    if cand_rate < base_rate:
        return TaskChange.WORSE
    return TaskChange.UNCHANGED


def compare_benchmarks(
    baseline: BenchmarkRun,
    candidate: BenchmarkRun,
    *,
    baseline_analysis: FailureAnalysis | None = None,
    candidate_analysis: FailureAnalysis | None = None,
) -> BenchmarkComparison:
    """Compare two benchmark runs over the tasks both ran.

    Runs are only comparable when they used the same suite id and version,
    identical definitions for the compared tasks and the same result class:
    offline (scripted) and real-model results are never compared.
    """
    reasons: list[str] = []
    notes: list[str] = []
    if baseline.result_class != candidate.result_class:
        reasons.append(
            f"result classes differ ({baseline.result_class.value} vs "
            f"{candidate.result_class.value}): offline and real-model results are never compared"
        )
    if baseline.suite_id != candidate.suite_id:
        reasons.append(f"different suites ({baseline.suite_id} vs {candidate.suite_id})")
    elif baseline.suite.version != candidate.suite.version:
        reasons.append(
            f"different suite versions ({baseline.suite.version} vs {candidate.suite.version})"
        )
    base_tasks = {r.task_id for r in baseline.results}
    cand_tasks = {r.task_id for r in candidate.results}
    common = [t.id for t in baseline.suite.tasks if t.id in base_tasks & cand_tasks]
    if not reasons:
        changed = [
            t
            for t in common
            if baseline.suite.task(t).model_dump() != candidate.suite.task(t).model_dump()
        ]
        if changed:
            reasons.append(
                "task definitions changed without a suite version bump: " + ", ".join(changed)
            )
        if not common:
            reasons.append("no tasks in common")
    if base_tasks != cand_tasks and common:
        notes.append("the runs covered different tasks; only the common tasks are compared")

    result = BenchmarkComparison(
        baseline_id=baseline.id,
        candidate_id=candidate.id,
        suite_id=baseline.suite_id,
        suite_version=baseline.suite.version,
        result_class=baseline.result_class,
        comparable=not reasons,
        reasons=reasons,
        notes=notes,
        verdict=Verdict.NOT_COMPARABLE,
    )
    if reasons:
        return result

    base_results = [r for r in baseline.results if r.task_id in common]
    cand_results = [r for r in candidate.results if r.task_id in common]
    b, c = _side(baseline, base_results), _side(candidate, cand_results)
    result.baseline, result.candidate = b, c
    result.pass_rate_delta = round(c.pass_rate - b.pass_rate, 4)
    result.mean_score_delta = round(c.mean_score - b.mean_score, 4)
    if b.mean_steps is not None and c.mean_steps is not None:
        result.mean_steps_delta = round(c.mean_steps - b.mean_steps, 2)

    for task_id in common:
        bt = [r for r in base_results if r.task_id == task_id]
        ct = [r for r in cand_results if r.task_id == task_id]
        bp, cp = sum(r.passed for r in bt), sum(r.passed for r in ct)
        b_rate, c_rate = bp / len(bt), cp / len(ct)
        result.tasks.append(
            TaskDelta(
                task_id=task_id,
                baseline_passed=bp,
                baseline_runs=len(bt),
                candidate_passed=cp,
                candidate_runs=len(ct),
                pass_rate_delta=round(c_rate - b_rate, 4),
                change=_task_change(b_rate, c_rate),
            )
        )

    if b.pass_rate_ci95 and c.pass_rate_ci95:
        result.significant = (
            c.pass_rate_ci95[0] > b.pass_rate_ci95[1] or c.pass_rate_ci95[1] < b.pass_rate_ci95[0]
        )
    if all(t.change == TaskChange.UNCHANGED for t in result.tasks):
        result.verdict = Verdict.UNCHANGED
    elif result.significant:
        result.verdict = Verdict.IMPROVED if result.pass_rate_delta > 0 else Verdict.REGRESSED
    else:
        result.verdict = Verdict.INCONCLUSIVE
        result.notes.append(
            "the 95% intervals overlap: run more repeats before concluding "
            "that the change helped or hurt"
        )

    if baseline_analysis is not None and candidate_analysis is not None:
        before = Counter(baseline_analysis.categories)
        after = Counter(candidate_analysis.categories)
        result.categories = [
            CategoryDelta(category=cat, baseline=before.get(cat, 0), candidate=after.get(cat, 0))
            for cat in sorted(set(before) | set(after), key=lambda k: -(before[k] + after[k]))
        ]
    if baseline.result_class == ResultClass.OFFLINE:
        result.notes.append(
            "offline (scripted) results are deterministic replays: they validate the pipeline "
            "and the benchmark, not a model; intervals over repeated replays are not evidence "
            "of model behaviour"
        )
    return result
