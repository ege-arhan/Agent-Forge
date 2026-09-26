"""Improvement proposals: concrete, reviewable config changes derived from a failure analysis.

The built-in proposer is rule-based and deterministic: every change cites the
failure category it addresses, the evidence (run ids) and its rationale.
Proposals can also be written by a developer (``proposer="manual"``). Either
way, changes are limited to an allowlist of agent-config paths; the provider
can never change, so a new version stays in the same result class
(offline/real) as its baseline.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentforge.benchmarks.runner import ResultClass
from agentforge.benchmarks.spec import BenchmarkSuite
from agentforge.core.config import AgentConfig
from agentforge.core.errors import ImprovementError
from agentforge.improvement.analysis import (
    NON_AGENT_CATEGORIES,
    FailureAnalysis,
    FailureCategory,
)

ALLOWED_PATHS = frozenset(
    {
        "system_prompt",
        "tools",
        "model.model",
        "model.temperature",
        "model.max_tokens",
        "limits.max_steps",
        "limits.timeout_seconds",
        "limits.max_tool_calls",
        "limits.max_consecutive_tool_errors",
        "retry.llm_max_attempts",
        "retry.evaluation_retries",
        "planner.strategy",
        "planner.max_plan_steps",
        "memory.enabled",
        "memory.recall_limit",
        "memory.keep_recent_messages",
    }
)


class ChangeOperation(StrEnum):
    SET = "set"
    APPEND = "append"  # text appended as a new paragraph (system_prompt)


class ProposedChange(BaseModel):
    id: str = ""
    path: str = Field(description="Dotted AgentConfig path, e.g. limits.max_steps.")
    operation: ChangeOperation = ChangeOperation.SET
    value: Any
    current: Any = None
    rationale: str = ""
    addresses: list[FailureCategory] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Run ids supporting the change.")


class ImprovementProposal(BaseModel):
    proposer: str = "rules"
    changes: list[ProposedChange] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list, description="Findings that no config change addresses."
    )


# ----------------------------------------------------------------- applying
def _get(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _set(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def validate_change(change: ProposedChange) -> None:
    if change.path not in ALLOWED_PATHS:
        raise ImprovementError(
            f"'{change.path}' cannot be changed by an improvement "
            f"(allowed: {', '.join(sorted(ALLOWED_PATHS))})"
        )
    if change.operation == ChangeOperation.APPEND and change.path != "system_prompt":
        raise ImprovementError("'append' is only supported for system_prompt")


def apply_changes(config: AgentConfig, changes: list[ProposedChange]) -> AgentConfig:
    """Return a new config with ``changes`` applied (validated; provider unchanged)."""
    data = config.model_dump(mode="json")
    for change in changes:
        validate_change(change)
        if change.operation == ChangeOperation.APPEND:
            current = str(_get(data, change.path) or "").rstrip()
            addition = str(change.value).strip()
            _set(data, change.path, f"{current}\n\n{addition}" if current else addition)
        else:
            _set(data, change.path, change.value)
    try:
        updated = AgentConfig.model_validate(data)
    except ValueError as exc:
        raise ImprovementError(f"the proposed changes produce an invalid config: {exc}") from exc
    if updated.model.provider != config.model.provider:  # pragma: no cover - path allowlist
        raise ImprovementError("improvements cannot change the provider")
    return updated


def prepare_manual(config: AgentConfig, changes: list[ProposedChange]) -> ImprovementProposal:
    """Validate developer-written changes and fill in ids/current values."""
    if not changes:
        raise ImprovementError("a manual proposal needs at least one change")
    data = config.model_dump(mode="json")
    prepared = []
    for index, change in enumerate(changes, 1):
        validate_change(change)
        prepared.append(
            change.model_copy(update={"id": f"c{index}", "current": _get(data, change.path)})
        )
    apply_changes(config, prepared)  # fail early on invalid values
    return ImprovementProposal(proposer="manual", changes=prepared)


# ---------------------------------------------------------------- proposing
PROMPT_LESSONS: dict[FailureCategory, str] = {
    FailureCategory.TESTS_FAILED: (
        "Before giving your final answer, run the relevant tests (and any command the task "
        "names) and keep working until they pass. Do not modify existing tests unless the "
        "task asks you to."
    ),
    FailureCategory.WORKSPACE_STATE: (
        "Create or modify exactly the files the task names, at the exact paths and in the "
        "requested format, then read them back to verify before finishing."
    ),
    FailureCategory.WRONG_OUTPUT: (
        "State the final result explicitly in your final answer, in the format the task asks for."
    ),
    FailureCategory.NO_FINAL_ANSWER: (
        "When the work is done, always end with a final answer that summarises the result."
    ),
    FailureCategory.PROCESS_NOT_FOLLOWED: (
        "Follow the process the task prescribes (for example: reproduce the problem first, use "
        "the requested tools, work on the requested branch, commit when asked)."
    ),
    FailureCategory.JUDGE_REJECTED: (
        "Re-read the task's requirements and check each one explicitly before finishing."
    ),
    FailureCategory.INEFFICIENT: (
        "Work efficiently: plan before acting, batch related edits, do not re-read files you "
        "have already inspected, and stop as soon as the result is verified."
    ),
    FailureCategory.TOOL_ERRORS: (
        "When a tool call fails, read the error and fix the arguments or change approach; never "
        "repeat an identical failing call. Tool arguments must match the tool's schema."
    ),
}

_EFFICIENCY = PROMPT_LESSONS[FailureCategory.INEFFICIENT]
_TIMEOUT_LESSON = (
    "Avoid long-running or interactive commands; prefer quick, non-interactive checks."
)


def _task_caps(suite: BenchmarkSuite, task_ids: set[str]) -> tuple[int, float]:
    steps = [suite.task(t).max_steps or suite.defaults.max_steps for t in task_ids]
    timeouts = [suite.task(t).timeout_seconds or suite.defaults.timeout_seconds for t in task_ids]
    return max(steps, default=suite.defaults.max_steps), max(
        timeouts, default=suite.defaults.timeout_seconds
    )


class _Builder:
    def __init__(self, analysis: FailureAnalysis, config: AgentConfig) -> None:
        self.analysis = analysis
        self.config = config
        self.data = config.model_dump(mode="json")
        self.changes: list[ProposedChange] = []
        self.notes: list[str] = []

    def runs_for(self, category: FailureCategory) -> list[str]:
        return [f.run_id for f in self.analysis.failures if f.category == category]

    def tasks_for(self, category: FailureCategory) -> set[str]:
        return {f.task_id for f in self.analysis.failures if f.category == category}

    def set(self, path: str, value: Any, category: FailureCategory, rationale: str) -> None:
        if any(c.path == path for c in self.changes):
            return
        self.changes.append(
            ProposedChange(
                path=path,
                value=value,
                current=_get(self.data, path),
                rationale=rationale,
                addresses=[category],
                evidence=self.runs_for(category)[:10],
            )
        )

    def lesson(self, text: str, category: FailureCategory, rationale: str) -> None:
        if text in self.config.system_prompt:
            self.notes.append(
                f"{category.value}: the system prompt already contains the matching guidance; "
                "consider a different change (e.g. a stronger model or more specific prompt)."
            )
            return
        for change in self.changes:
            if change.path == "system_prompt" and change.value == text:
                change.addresses.append(category)
                return
        self.changes.append(
            ProposedChange(
                path="system_prompt",
                operation=ChangeOperation.APPEND,
                value=text,
                current=None,
                rationale=rationale,
                addresses=[category],
                evidence=self.runs_for(category)[:10],
            )
        )


def propose(
    analysis: FailureAnalysis, config: AgentConfig, suite: BenchmarkSuite
) -> ImprovementProposal:
    """Deterministic, rule-based proposal for the failures in ``analysis``."""
    b = _Builder(analysis, config)
    limits, retry = config.limits, config.retry
    for name, count in analysis.categories.items():
        category = FailureCategory(name)
        runs = f"{count} failed run(s)"
        if category in NON_AGENT_CATEGORIES:
            b.notes.append(
                f"{category.value}: {runs} failed for reasons outside the agent "
                "(benchmark, environment or operator); fix those before judging the agent."
            )
        elif category == FailureCategory.STEP_LIMIT:
            cap, _ = _task_caps(suite, b.tasks_for(category))
            if limits.max_steps < cap:
                b.set(
                    "limits.max_steps",
                    cap,
                    category,
                    f"{runs} stopped at the agent's step limit ({limits.max_steps}) while the "
                    f"suite allows up to {cap} steps for these tasks.",
                )
            else:
                b.lesson(
                    _EFFICIENCY,
                    category,
                    f"{runs} reached the suite's step cap ({cap}); the agent must use fewer "
                    "steps (limits cannot be raised above the benchmark's cap).",
                )
        elif category == FailureCategory.TIMEOUT:
            _, cap_t = _task_caps(suite, b.tasks_for(category))
            if limits.timeout_seconds < cap_t:
                b.set(
                    "limits.timeout_seconds",
                    cap_t,
                    category,
                    f"{runs} timed out at the agent's limit ({limits.timeout_seconds:g}s) while "
                    f"the suite allows {cap_t:g}s for these tasks.",
                )
            else:
                b.lesson(
                    _TIMEOUT_LESSON,
                    category,
                    f"{runs} hit the suite's time cap ({cap_t:g}s).",
                )
        elif category == FailureCategory.TOOL_BUDGET:
            b.set(
                "limits.max_tool_calls",
                min(5_000, max(limits.max_tool_calls * 2, limits.max_tool_calls + 10)),
                category,
                f"{runs} exhausted the tool-call budget ({limits.max_tool_calls}).",
            )
        elif category == FailureCategory.LLM_ERROR:
            if retry.llm_max_attempts < 6:
                b.set(
                    "retry.llm_max_attempts",
                    min(10, retry.llm_max_attempts + 2),
                    category,
                    f"{runs} ended with a provider error after {retry.llm_max_attempts} "
                    "attempt(s); more retries help only with transient errors - check evidence.",
                )
            else:
                b.notes.append(f"{category.value}: {runs}; retries are already high.")
        elif category == FailureCategory.LLM_REFUSAL:
            b.notes.append(
                f"{category.value}: {runs}; review the task wording and the system prompt."
            )
        elif category in PROMPT_LESSONS:
            b.lesson(
                PROMPT_LESSONS[category],
                category,
                f"{runs} failed with '{category.value}'.",
            )
        else:
            b.notes.append(
                f"{category.value}: {runs}; inspect the evidence - no rule-based change applies."
            )

    invalid = sum(v.get("invalid_input", 0) for v in analysis.tool_issues.values())
    if invalid and not any(FailureCategory.TOOL_ERRORS in c.addresses for c in b.changes):
        b.notes.append(
            f"{invalid} tool call(s) had invalid arguments across all runs "
            f"({', '.join(t for t, v in analysis.tool_issues.items() if v.get('invalid_input'))})."
        )
    if analysis.result_class == ResultClass.OFFLINE and any(
        c.path == "system_prompt" for c in b.changes
    ):
        b.notes.append(
            "Offline (scripted) agents replay fixed turns: prompt changes cannot affect their "
            "results. Evaluate prompt changes with a real model provider."
        )
    for index, change in enumerate(b.changes, 1):
        change.id = f"c{index}"
    return ImprovementProposal(proposer="rules", changes=b.changes, notes=b.notes)


def describe(changes: list[ProposedChange]) -> str:
    """One-line human summary of a set of changes (used as the version's change summary)."""
    parts = []
    for c in changes:
        if c.operation == ChangeOperation.APPEND:
            parts.append(f"{c.path} += {_short(c.value)}")
        else:
            parts.append(f"{c.path}: {c.current!r} -> {c.value!r}")
    return "; ".join(parts)


def _short(value: Any, limit: int = 60) -> str:
    text = str(value).strip().replace("\n", " ")
    return repr(text if len(text) <= limit else text[: limit - 1] + "…")


__all__ = [
    "ALLOWED_PATHS",
    "ChangeOperation",
    "ImprovementProposal",
    "ProposedChange",
    "apply_changes",
    "describe",
    "prepare_manual",
    "propose",
    "validate_change",
]
