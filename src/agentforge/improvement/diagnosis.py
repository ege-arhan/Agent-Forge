"""Trace-level diagnosis: *where* in its work a failed run went wrong.

The failure category (``analysis.py``) says what stopped a run or which check
failed. The diagnosis reads the recorded trace - the ordered tool calls, the
plan and the evaluator results - and adds two things:

* **signals**: facts observed in the trace (e.g. "the same call was repeated
  four times", "the run ended right after its last file change");
* a **stage**: the earliest phase of the work those facts point to (planning,
  execution, verification, reasoning or reporting).

Everything is rule-based and deterministic; no model reads the trace. The
stage is a heuristic reading of the signals, not a proven cause: it tells a
developer where to look first. ``reasoning`` in particular is a residual - the
trace shows no process defect, so the defect is in what the agent wrote or
concluded - and ``undetermined`` is reported when the rules do not apply.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, Field

from agentforge.core.config import PlannerStrategy
from agentforge.core.models import Run, RunStatus, ToolCallRecord, ToolCallStatus
from agentforge.tools.base import Permission


class ToolPhase(StrEnum):
    """What a tool call does to the workspace, derived from the tool's permissions."""

    EXPLORE = "explore"  # read-only: files, git, GitHub
    MODIFY = "modify"  # writes files, git or GitHub state
    EXECUTE = "execute"  # runs a process (may read, write or test - not knowable)
    OTHER = "other"  # network, memory, or a tool this process does not know


class FailureStage(StrEnum):
    PLANNING = "planning"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    REASONING = "reasoning"
    REPORTING = "reporting"
    UNDETERMINED = "undetermined"


class TraceSignal(StrEnum):
    NO_TOOL_CALLS = "no_tool_calls"
    READ_ONLY = "read_only"
    PLAN_MISSING = "plan_missing"
    REPEATED_CALL = "repeated_call"
    TRAILING_TOOL_ERRORS = "trailing_tool_errors"
    UNVERIFIED_CHANGE = "unverified_change"
    LAST_COMMAND_FAILED = "last_command_failed"


STAGE_DESCRIPTIONS: dict[FailureStage, str] = {
    FailureStage.PLANNING: (
        "The task required a change to the workspace, but the agent never attempted one."
    ),
    FailureStage.EXECUTION: (
        "The agent worked on the task but its actions failed, repeated or ran out of budget."
    ),
    FailureStage.VERIFICATION: (
        "The agent changed the workspace and finished without a passing check of its own."
    ),
    FailureStage.REASONING: (
        "The trace shows no process defect; what the agent wrote or concluded was wrong."
    ),
    FailureStage.REPORTING: (
        "The workspace checks passed; only the final answer failed its check."
    ),
    FailureStage.UNDETERMINED: "The trace rules do not single out a stage.",
}

SIGNAL_DESCRIPTIONS: dict[TraceSignal, str] = {
    TraceSignal.NO_TOOL_CALLS: "The agent made no tool calls.",
    TraceSignal.READ_ONLY: "No call changed a file and no command was run.",
    TraceSignal.PLAN_MISSING: "The plan-execute strategy was configured but no plan was recorded.",
    TraceSignal.REPEATED_CALL: (
        "An identical call was made three or more times with no change in between."
    ),
    TraceSignal.TRAILING_TOOL_ERRORS: "The last tool calls of the run all failed.",
    TraceSignal.UNVERIFIED_CHANGE: (
        "The run ended right after its last change, without reading or running anything."
    ),
    TraceSignal.LAST_COMMAND_FAILED: "The last command the agent ran reported a failure.",
}

REPEAT_THRESHOLD = 3
_TRAILING_ERRORS = 2

_WRITE = frozenset({Permission.FS_WRITE, Permission.GIT_WRITE, Permission.GITHUB_WRITE})
_READ = frozenset({Permission.FS_READ, Permission.GIT_READ, Permission.GITHUB_READ})

# Evaluator types that inspect the workspace / the final answer.
_WORKSPACE_EVALUATORS = frozenset({"command", "file_exists", "file_contains"})
_OUTPUT_EVALUATORS = frozenset({"output_contains", "output_matches", "completed"})
# Error types of a run that was stopped before the agent finished.
_STOPPED_ERRORS = frozenset({"max_steps", "token_budget", "tool_errors", "timeout"})
# Error types the trace cannot explain (infrastructure, provider, operator).
_NOT_DIAGNOSED_PREFIXES = ("setup", "cancelled", "llm.")


class TraceDiagnosis(BaseModel):
    stage: FailureStage
    signals: list[TraceSignal] = Field(default_factory=list)
    summary: str
    details: list[str] = Field(
        default_factory=list, description="One line per signal, with what was observed."
    )
    phases: dict[str, int] = Field(
        default_factory=dict, description="Tool phase -> number of calls in the run."
    )


def phase_of(permissions: frozenset[Permission]) -> ToolPhase:
    if Permission.PROCESS_EXEC in permissions:
        return ToolPhase.EXECUTE
    if permissions & _WRITE:
        return ToolPhase.MODIFY
    if permissions and permissions <= _READ:
        return ToolPhase.EXPLORE
    return ToolPhase.OTHER


def registry_phases() -> dict[str, ToolPhase]:
    """Phase of every tool in the process-wide registry (built-ins and plugins)."""
    from agentforge.tools.registry import default_registry

    registry = default_registry()
    return {
        name: phase_of(registry.get(name).permissions)
        for names in registry.toolsets().values()
        for name in names
    }


def _call_key(call: ToolCallRecord) -> str:
    return call.tool + " " + json.dumps(call.arguments, sort_keys=True, default=str)


def _command_failed(call: ToolCallRecord) -> bool:
    if call.status != ToolCallStatus.SUCCESS:
        return True
    # run_command reports a non-zero exit code in its output instead of failing.
    first = call.output.splitlines()[0] if call.output else ""
    if first.startswith("exit_code:"):
        return first.removeprefix("exit_code:").strip() != "0"
    return False


def _repeated(calls: list[tuple[ToolCallRecord, ToolPhase]]) -> tuple[ToolCallRecord, int] | None:
    """The most repeated identical call within a stretch where nothing changed."""
    counts: Counter[str] = Counter()
    best: tuple[ToolCallRecord, int] | None = None
    last_execute = ""
    for call, phase in calls:
        key = _call_key(call)
        ok = call.status == ToolCallStatus.SUCCESS
        # A change (or a different command, which may have made one) starts a new
        # stretch: re-running the tests after an edit is not a loop.
        if ok and (
            phase == ToolPhase.MODIFY or (phase == ToolPhase.EXECUTE and key != last_execute)
        ):
            counts.clear()
        if phase == ToolPhase.EXECUTE:
            last_execute = key
        counts[key] += 1
        if counts[key] >= REPEAT_THRESHOLD and (best is None or counts[key] > best[1]):
            best = (call, counts[key])
    return best


def _evaluator_kinds(run: Run) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for spec in run.evaluators:
        kind = str(spec.get("type", ""))
        kinds[str(spec.get("name") or kind)] = kind
    return kinds


def diagnose_run(run: Run, phases: Mapping[str, ToolPhase] | None = None) -> TraceDiagnosis | None:
    """Diagnose a failed run from its trace.

    ``None`` when the run passed or failed for a reason its trace cannot explain
    (setup, cancellation, provider errors and refusals, internal errors).
    """
    if run.evaluation is not None and run.evaluation.passed:
        return None
    error_type = run.error.type if run.error else ""
    if error_type.startswith(_NOT_DIAGNOSED_PREFIXES) or run.status == RunStatus.CANCELLED:
        return None
    stopped = error_type in _STOPPED_ERRORS or run.status == RunStatus.TIMED_OUT
    if run.error is not None and not stopped:
        return None  # internal or unknown error

    known = registry_phases() if phases is None else phases
    calls = [(call, known.get(call.tool, ToolPhase.OTHER)) for call in run.tool_calls]
    phase_counts = Counter(phase.value for _, phase in calls)
    succeeded = [(c, p) for c, p in calls if c.status == ToolCallStatus.SUCCESS]

    kinds = _evaluator_kinds(run)
    expects_change = any(kind in _WORKSPACE_EVALUATORS for kind in kinds.values())

    signals: list[TraceSignal] = []
    details: list[str] = []

    def add(signal: TraceSignal, observed: str = "") -> None:
        signals.append(signal)
        details.append(SIGNAL_DESCRIPTIONS[signal] + (f" ({observed})" if observed else ""))

    if not calls:
        add(TraceSignal.NO_TOOL_CALLS)
    elif not any(p == ToolPhase.MODIFY for _, p in succeeded) and not any(
        p == ToolPhase.EXECUTE for _, p in calls
    ):
        add(TraceSignal.READ_ONLY, f"{len(calls)} call(s)")
    if run.config.planner.strategy == PlannerStrategy.PLAN_EXECUTE and not run.plan:
        add(TraceSignal.PLAN_MISSING)

    repeated = _repeated(calls)
    if repeated is not None:
        add(TraceSignal.REPEATED_CALL, f"{repeated[0].tool} x{repeated[1]}")

    trailing = 0
    for call, _ in reversed(calls):
        if call.status == ToolCallStatus.SUCCESS:
            break
        trailing += 1
    if trailing >= _TRAILING_ERRORS:
        add(TraceSignal.TRAILING_TOOL_ERRORS, f"last {trailing} call(s)")

    last_modify = max(
        (
            i
            for i, (c, p) in enumerate(calls)
            if p == ToolPhase.MODIFY and c.status == ToolCallStatus.SUCCESS
        ),
        default=None,
    )
    if (
        last_modify is not None
        and not stopped
        and not any(
            p in (ToolPhase.EXPLORE, ToolPhase.EXECUTE) for _, p in calls[last_modify + 1 :]
        )
    ):
        add(TraceSignal.UNVERIFIED_CHANGE, f"after {calls[last_modify][0].tool}")

    commands = [c for c, p in calls if p == ToolPhase.EXECUTE]
    if commands and _command_failed(commands[-1]):
        add(TraceSignal.LAST_COMMAND_FAILED, commands[-1].tool)

    stage = _stage(run, set(signals), kinds, expects_change=expects_change, stopped=stopped)
    summary = STAGE_DESCRIPTIONS[stage]
    if stage == FailureStage.PLANNING and stopped:
        summary += " It was stopped by a limit while still exploring."
    return TraceDiagnosis(
        stage=stage,
        signals=signals,
        summary=summary,
        details=details,
        phases=dict(sorted(phase_counts.items())),
    )


def _stage(
    run: Run,
    signals: set[TraceSignal],
    kinds: dict[str, str],
    *,
    expects_change: bool,
    stopped: bool,
) -> FailureStage:
    results = run.evaluation.results if run.evaluation is not None else []
    failed = {kinds.get(r.name, r.name) for r in results if not r.passed and r.required}
    workspace = [r for r in results if kinds.get(r.name, r.name) in _WORKSPACE_EVALUATORS]

    if (
        not stopped
        and workspace
        and all(r.passed for r in workspace)
        and failed
        and failed <= _OUTPUT_EVALUATORS
    ):
        return FailureStage.REPORTING
    if expects_change and signals & {TraceSignal.NO_TOOL_CALLS, TraceSignal.READ_ONLY}:
        return FailureStage.PLANNING
    if stopped or signals & {TraceSignal.REPEATED_CALL, TraceSignal.TRAILING_TOOL_ERRORS}:
        return FailureStage.EXECUTION
    if expects_change and signals & {
        TraceSignal.UNVERIFIED_CHANGE,
        TraceSignal.LAST_COMMAND_FAILED,
    }:
        return FailureStage.VERIFICATION
    if failed & (_WORKSPACE_EVALUATORS | (_OUTPUT_EVALUATORS - {"completed"})):
        return FailureStage.REASONING
    return FailureStage.UNDETERMINED


__all__ = [
    "REPEAT_THRESHOLD",
    "SIGNAL_DESCRIPTIONS",
    "STAGE_DESCRIPTIONS",
    "FailureStage",
    "ToolPhase",
    "TraceDiagnosis",
    "TraceSignal",
    "diagnose_run",
    "phase_of",
    "registry_phases",
]
