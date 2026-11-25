"""Optional model-assisted proposer (``proposer="llm"``).

A model configured by the operator reads the failure analysis and the agent's
current settings and suggests configuration changes. Its answer is treated as
untrusted input: every suggested change is validated, and anything outside the
rules below is dropped with a note instead of being recorded.

What the model is shown, and what it is not:

* It sees the agent's values at the changeable paths (the system prompt among
  them), the failure categories and trace-diagnosis stages and signals with
  their counts, per failed run the task id, category, stage and signals, the
  tool issue counts and the suite's step and time caps.
* It never sees text produced by a run or by an evaluator: no evaluator
  details, no error messages, no tool arguments or outputs, no task goals.
  Hidden checks therefore cannot leak into a prompt it writes, and a run
  cannot plant instructions for it.

What it may change is narrower than the manual allowlist: not ``tools`` (it
would widen what the agent may do), not ``model.model`` (it changes what is
measured and what it costs) and not ``retry.evaluation_retries`` (it shows the
agent the checks). The system prompt can only be appended to.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from agentforge.benchmarks.runner import ResultClass
from agentforge.benchmarks.spec import BenchmarkSuite
from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.core.errors import AgentForgeError, ImprovementError
from agentforge.improvement.analysis import (
    CATEGORY_DESCRIPTIONS,
    NON_AGENT_CATEGORIES,
    FailureAnalysis,
    FailureCategory,
)
from agentforge.improvement.diagnosis import SIGNAL_DESCRIPTIONS, STAGE_DESCRIPTIONS
from agentforge.improvement.proposal import (
    ALLOWED_PATHS,
    ChangeOperation,
    ImprovementProposal,
    ProposedChange,
    ProposerCall,
    _get,
    _task_caps,
    apply_changes,
)
from agentforge.llm.pricing import PriceTable
from agentforge.observability.redaction import Redactor

LLM_EXCLUDED_PATHS = frozenset({"tools", "model.model", "retry.evaluation_retries"})
LLM_ALLOWED_PATHS = ALLOWED_PATHS - LLM_EXCLUDED_PATHS

MAX_CHANGES = 8
MAX_LESSON_CHARS = 1200
MAX_RATIONALE_CHARS = 500
MAX_NOTES = 10
MAX_NOTE_CHARS = 300
MAX_FAILURES_SHOWN = 40
CALL_TIMEOUT_SECONDS = 120.0

SYSTEM_PROMPT = """\
You review why an AI agent failed benchmark tasks and propose changes to the \
agent's configuration. You are given the agent's current settings, the failure \
categories, a rule-based diagnosis of each failed run and the benchmark's limits. \
You are not given the tasks or the checks, so do not guess at them.

Respond with a single JSON object and nothing else:
{"changes": [{"path": "<setting>", "operation": "set" | "append", "value": <new value>,
              "rationale": "<one or two sentences>", "addresses": ["<failure category>"]}],
 "notes": ["<finding that no setting change addresses>"]}

Rules:
- "path" must be one of the settings listed under "changeable". Nothing else can change.
- "system_prompt" accepts only the operation "append": general working guidance for the
  agent, at most __LESSON__ characters, that is not already in the prompt. Every other
  setting takes "set" with a number, a boolean or a string.
- "limits.max_steps" and "limits.timeout_seconds" cannot usefully exceed the benchmark's
  caps given under "suite_caps".
- At most __CHANGES__ changes. Propose fewer, well-founded changes rather than many. If no
  setting change would plausibly help, return an empty "changes" list and say why in
  "notes".
- Failures in a category marked "agent_problem": false come from the benchmark or the
  environment; do not propose changes for them.
""".replace("__LESSON__", str(MAX_LESSON_CHARS)).replace("__CHANGES__", str(MAX_CHANGES))


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _failed_task_caps(analysis: FailureAnalysis, suite: BenchmarkSuite) -> tuple[int, float]:
    known = {task.id for task in suite.tasks}
    return _task_caps(suite, {f.task_id for f in analysis.failures if f.task_id in known})


def build_context(
    analysis: FailureAnalysis, config: AgentConfig, suite: BenchmarkSuite
) -> dict[str, Any]:
    """The document sent to the proposer model (see the module docstring for its limits)."""
    data = config.model_dump(mode="json")
    cap_steps, cap_timeout = _failed_task_caps(analysis, suite)
    categories = []
    for name, count in analysis.categories.items():
        category = FailureCategory(name)
        categories.append(
            {
                "category": name,
                "failed_runs": count,
                "meaning": CATEGORY_DESCRIPTIONS[category],
                "agent_problem": category not in NON_AGENT_CATEGORIES,
            }
        )
    failures = []
    for failure in analysis.failures[:MAX_FAILURES_SHOWN]:
        item: dict[str, Any] = {
            "task": failure.task_id,
            "category": failure.category.value,
            "also": [c.value for c in failure.secondary],
        }
        if failure.diagnosis is not None:
            item["stage"] = failure.diagnosis.stage.value
            item["signals"] = [s.value for s in failure.diagnosis.signals]
        failures.append(item)
    stages = {s.value: text for s, text in STAGE_DESCRIPTIONS.items() if s.value in analysis.stages}
    signals = {
        s.value: text for s, text in SIGNAL_DESCRIPTIONS.items() if s.value in analysis.signals
    }
    return {
        "agent": {"name": config.name, "provider": config.model.provider},
        "changeable": {path: _get(data, path) for path in sorted(LLM_ALLOWED_PATHS)},
        "tools": list(config.tools),
        "suite_caps": {"limits.max_steps": cap_steps, "limits.timeout_seconds": cap_timeout},
        "runs": {"total": analysis.runs, "passed": analysis.passed, "failed": analysis.failed},
        "failure_categories": categories,
        "diagnosis": {
            "stage_counts": analysis.stages,
            "signal_counts": analysis.signals,
            "stage_meanings": stages,
            "signal_meanings": signals,
        },
        "failed_runs": failures,
        "tool_issue_counts": analysis.tool_issues,
    }


def parse_answer(text: str) -> dict[str, Any]:
    """Extract the first JSON object with a ``changes`` or ``notes`` key from the model's text."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict) and ("changes" in value or "notes" in value):
            return value
        start = text.find("{", start + 1)
    raise ImprovementError("the proposer model did not return the requested JSON object")


def validate_suggestions(
    answer: dict[str, Any],
    analysis: FailureAnalysis,
    config: AgentConfig,
    suite: BenchmarkSuite,
    redactor: Redactor,
) -> tuple[list[ProposedChange], list[str]]:
    """Turn the model's answer into validated changes; return them with notes on what was dropped.

    Nothing in ``answer`` is trusted: paths, operations, values, text lengths
    and categories are all checked here, and the evidence run ids are taken
    from the analysis, never from the model.
    """
    data = config.model_dump(mode="json")
    cap_steps, cap_timeout = _failed_task_caps(analysis, suite)
    caps: dict[str, float] = {"limits.max_steps": cap_steps, "limits.timeout_seconds": cap_timeout}
    seen_categories = set(analysis.categories) | {
        c.value for f in analysis.failures for c in f.secondary
    }

    changes: list[ProposedChange] = []
    notes: list[str] = []
    raw_notes = answer.get("notes")
    for note in raw_notes if isinstance(raw_notes, list) else []:
        if isinstance(note, str) and note.strip() and len(notes) < MAX_NOTES:
            notes.append(redactor.redact_text(_clip(note, MAX_NOTE_CHARS)))

    def drop(what: str, why: str) -> None:
        notes.append(f"dropped a suggested change ({_clip(what, 60)}): {why}")

    raw_changes = answer.get("changes")
    if not isinstance(raw_changes, list):
        raw_changes = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            drop("not an object", "a change must be a JSON object")
            continue
        path = raw.get("path")
        if not isinstance(path, str) or path not in LLM_ALLOWED_PATHS:
            drop(str(path), "this setting cannot be changed by the model-assisted proposer")
            continue
        if len(changes) >= MAX_CHANGES:
            drop(path, f"more than {MAX_CHANGES} changes were suggested")
            continue
        value = raw.get("value")
        current = _get(data, path)
        if path == "system_prompt":
            if raw.get("operation") != ChangeOperation.APPEND.value:
                drop(path, "the system prompt can only be appended to")
                continue
            if not isinstance(value, str) or not value.strip():
                drop(path, "the text to append is empty or not a string")
                continue
            value = redactor.redact_text(value.strip())
            if len(value) > MAX_LESSON_CHARS:
                drop(path, f"the text to append is longer than {MAX_LESSON_CHARS} characters")
                continue
            if value in config.system_prompt or any(
                c.path == path and c.value == value for c in changes
            ):
                drop(path, "the prompt already contains this text")
                continue
            operation, current = ChangeOperation.APPEND, None
        else:
            if raw.get("operation", ChangeOperation.SET.value) != ChangeOperation.SET.value:
                drop(path, "only 'set' is supported for this setting")
                continue
            if isinstance(value, dict | list) or value is None:
                drop(path, "the value must be a number, a boolean or a string")
                continue
            if any(c.path == path for c in changes):
                drop(path, "the setting was suggested more than once; the first is kept")
                continue
            if isinstance(value, bool) != isinstance(current, bool):
                # Pydantic would read true as 1; a boolean is only valid for a boolean setting.
                drop(path, f"a {type(value).__name__} is not a valid value for this setting")
                continue
            if isinstance(value, str):
                value = redactor.redact_text(value)
            try:
                alone = apply_changes(config, [ProposedChange(path=path, value=value)])
            except ImprovementError as exc:
                drop(path, _clip(str(exc), 200))
                continue
            # Record the value as the config holds it ("12" for a number becomes 12).
            value = _get(alone.model_dump(mode="json"), path)
            cap = caps.get(path)
            if cap is not None and isinstance(value, int | float) and value > cap:
                notes.append(
                    f"{path}: the suggested {value:g} exceeds the suite's cap for the "
                    f"failed tasks and was lowered to {cap:g}."
                )
                value = cap
            if value == current:
                drop(path, f"the setting already has the value {current!r}")
                continue
            operation = ChangeOperation.SET
        raw_addresses = raw.get("addresses")
        addresses = [
            FailureCategory(a)
            for a in dict.fromkeys(raw_addresses if isinstance(raw_addresses, list) else [])
            if isinstance(a, str) and a in seen_categories
        ]
        rationale = raw.get("rationale")
        change = ProposedChange(
            path=path,
            operation=operation,
            value=value,
            current=current,
            rationale=redactor.redact_text(_clip(rationale, MAX_RATIONALE_CHARS))
            if isinstance(rationale, str)
            else "",
            addresses=addresses,
            evidence=[
                f.run_id
                for f in analysis.failures
                if f.category in addresses or set(f.secondary) & set(addresses)
            ][:10],
        )
        try:
            # Together with the changes kept so far: a combination can be invalid.
            apply_changes(config, [*changes, change])
        except ImprovementError as exc:
            drop(path, _clip(str(exc), 200))
            continue
        changes.append(change)

    for index, change in enumerate(changes, 1):
        change.id = f"c{index}"
    return changes, notes


async def propose_with_model(
    analysis: FailureAnalysis,
    config: AgentConfig,
    suite: BenchmarkSuite,
    model: ModelConfig,
    *,
    env: Mapping[str, str] | None = None,
    price_table: PriceTable | None = None,
    redactor: Redactor | None = None,
) -> ImprovementProposal:
    """Ask ``model`` for a proposal and validate its answer. One call, no retries."""
    from agentforge.llm.registry import create_provider
    from agentforge.llm.types import CompletionRequest, Message

    if analysis.failed == 0:
        return ImprovementProposal(
            proposer="llm", notes=["No failed runs: the proposer model was not called."]
        )
    redactor = redactor or Redactor.from_environment(env)
    context = redactor.redact(build_context(analysis, config, suite))
    request = CompletionRequest(
        model=model.model,
        system=SYSTEM_PROMPT,
        messages=[Message.user(json.dumps(context, indent=1, sort_keys=True, default=str))],
        max_tokens=model.max_tokens,
        temperature=model.temperature,
    )
    try:
        provider = create_provider(model, env)
        try:
            response = await asyncio.wait_for(
                provider.complete(request), timeout=CALL_TIMEOUT_SECONDS
            )
        finally:
            await provider.aclose()
    except TimeoutError as exc:
        raise ImprovementError(
            f"the proposer model did not answer within {CALL_TIMEOUT_SECONDS:g}s"
        ) from exc
    except ImprovementError:
        raise
    except AgentForgeError as exc:
        raise ImprovementError(
            f"the proposer model call failed: {redactor.redact_text(_clip(str(exc), 300))}"
        ) from exc

    changes, notes = validate_suggestions(
        parse_answer(response.message.text), analysis, config, suite, redactor
    )
    if analysis.result_class == ResultClass.OFFLINE and any(
        c.path == "system_prompt" for c in changes
    ):
        notes.append(
            "Offline (scripted) agents replay fixed turns: prompt changes cannot affect their "
            "results. Evaluate prompt changes with a real model provider."
        )
    prices = price_table or PriceTable()
    cost = prices.estimate(model.provider, response.model, response.usage)
    if cost is None:
        cost = prices.estimate(model.provider, model.model, response.usage)
    return ImprovementProposal(
        proposer="llm",
        changes=changes,
        notes=notes,
        proposer_call=ProposerCall(
            provider=model.provider,
            model=response.model or model.model,
            usage=response.usage,
            cost_usd=cost,
        ),
    )


__all__ = [
    "LLM_ALLOWED_PATHS",
    "LLM_EXCLUDED_PATHS",
    "SYSTEM_PROMPT",
    "build_context",
    "parse_answer",
    "propose_with_model",
    "validate_suggestions",
]
