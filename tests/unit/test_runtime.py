from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agentforge.core.config import PlannerConfig, PlannerStrategy, RetryPolicy, RunLimits
from agentforge.core.errors import LLMError
from agentforge.core.models import RunStatus, StepKind, ToolCallStatus
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.llm.base import LLMProvider
from agentforge.llm.types import CompletionRequest, CompletionResponse, Message, Role, StopReason
from agentforge.memory.base import InMemoryMemoryStore, MemoryRecord, MemoryScope
from agentforge.runtime.events import RunEvent
from agentforge.runtime.factory import prepare_run, run_agent
from agentforge.settings import Settings
from tests.conftest import scripted_config

FAST_RETRY = RetryPolicy(backoff_initial_seconds=0.0, backoff_max_seconds=0.0)


class Recorder:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def on_event(self, event: RunEvent, run: Any) -> None:
        self.events.append(event)

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.events]


def write_turns(path: str = "out.txt", content: str = "hello") -> list[dict[str, Any]]:
    return [
        {
            "text": "writing",
            "tool_calls": [{"name": "write_file", "arguments": {"path": path, "content": content}}],
        },
        {"text": "All done."},
    ]


async def test_successful_run_records_everything(settings: Settings) -> None:
    recorder = Recorder()
    run = await run_agent(
        scripted_config(write_turns()),
        "write a file",
        settings=settings,
        observers=[recorder],
        evaluators=[EvaluatorSpec(type="file_contains", path="out.txt", text="hello")],
    )
    assert run.status == RunStatus.SUCCEEDED
    assert run.result == "All done."
    assert run.started_at and run.finished_at and run.finished_at >= run.started_at
    assert [s.kind for s in run.steps] == [StepKind.ACTION, StepKind.ACTION, StepKind.EVALUATION]
    assert run.steps[0].tool_calls[0].status == ToolCallStatus.SUCCESS
    assert run.evaluation is not None and run.evaluation.passed
    assert run.metrics.tool_calls == 1 and run.metrics.tool_success_rate == 1.0
    assert run.metrics.cost_usd == 0.0
    assert recorder.types[0] == "run.started" and recorder.types[-1] == "run.finished"
    assert "tool.finished" in recorder.types and "evaluation.finished" in recorder.types


async def test_max_steps_fails_run(settings: Settings) -> None:
    turns = [{"tool_calls": [{"name": "list_directory", "arguments": {}}]}] * 10
    config = scripted_config(turns, limits=RunLimits(max_steps=3))
    run = await run_agent(config, "loop forever", settings=settings)
    assert run.status == RunStatus.FAILED
    assert run.error is not None and run.error.type == "max_steps"
    assert run.metrics.steps == 3


async def test_llm_retry_then_success(settings: Settings) -> None:
    turns = [{"error": {"message": "overloaded", "retryable": True}}, {"text": "ok"}]
    recorder = Recorder()
    run = await run_agent(
        scripted_config(turns, retry=FAST_RETRY), "g", settings=settings, observers=[recorder]
    )
    assert run.status == RunStatus.SUCCEEDED
    assert run.steps[0].llm_call is not None and run.steps[0].llm_call.attempts == 2
    assert run.metrics.llm_retries == 1
    assert "llm.retry" in recorder.types


async def test_llm_non_retryable_error_fails_run(settings: Settings) -> None:
    turns = [{"error": {"message": "bad request", "retryable": False}}]
    run = await run_agent(scripted_config(turns, retry=FAST_RETRY), "g", settings=settings)
    assert run.status == RunStatus.FAILED
    assert run.error is not None and run.error.type.startswith("llm.")
    assert run.steps[0].error is not None


async def test_llm_retries_exhausted(settings: Settings) -> None:
    turns = [{"error": {"message": "503", "retryable": True}}] * 5
    config = scripted_config(
        turns, retry=RetryPolicy(llm_max_attempts=2, backoff_initial_seconds=0)
    )
    run = await run_agent(config, "g", settings=settings)
    assert run.status == RunStatus.FAILED
    assert run.error is not None and run.error.retryable
    assert run.steps[0].llm_call is not None and run.steps[0].llm_call.attempts == 2


class SlowProvider(LLMProvider):
    name = "slow"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")


async def test_run_timeout(settings: Settings) -> None:
    config = scripted_config([], limits=RunLimits(timeout_seconds=0.2))
    prepared = prepare_run(config, "g", settings=settings, provider=SlowProvider())
    run = await prepared.execute()
    assert run.status == RunStatus.TIMED_OUT
    assert run.finished_at is not None


async def test_cooperative_cancellation(settings: Settings) -> None:
    prepared = prepare_run(scripted_config([]), "g", settings=settings, provider=SlowProvider())
    task = asyncio.create_task(prepared.execute())
    await asyncio.sleep(0.05)
    prepared.runtime.cancel()
    task.cancel()  # the provider call is blocked, so also cancel the task
    with pytest.raises(asyncio.CancelledError):
        await task
    assert prepared.run.status == RunStatus.CANCELLED
    assert prepared.run.finished_at is not None


async def test_cancel_before_start(settings: Settings) -> None:
    prepared = prepare_run(scripted_config(write_turns()), "g", settings=settings)
    prepared.runtime.cancel()
    run = await prepared.execute()
    assert run.status == RunStatus.CANCELLED


async def test_evaluation_retry_gives_feedback_and_recovers(settings: Settings) -> None:
    turns = [
        {"text": "I think it's done."},
        {
            "tool_calls": [
                {"name": "write_file", "arguments": {"path": "a.txt", "content": "fixed"}}
            ]
        },
        {"text": "Now really done."},
    ]
    config = scripted_config(turns, retry=RetryPolicy(evaluation_retries=1))
    prepared = prepare_run(config, "create a.txt", settings=settings)
    run = await prepared.execute([EvaluatorSpec(type="file_exists", path="a.txt")])
    assert run.status == RunStatus.SUCCEEDED
    assert run.evaluation is not None and run.evaluation.passed
    kinds = [s.kind for s in run.steps]
    assert kinds.count(StepKind.EVALUATION) == 2
    assert run.metrics.evaluation_retries == 1
    assert run.result == "Now really done."


async def test_failed_evaluation_without_retries_still_succeeds_execution(
    settings: Settings,
) -> None:
    run = await run_agent(
        scripted_config([{"text": "done"}]),
        "g",
        settings=settings,
        evaluators=[EvaluatorSpec(type="file_exists", path="missing.txt")],
    )
    assert run.status == RunStatus.SUCCEEDED  # execution completed...
    assert run.evaluation is not None and not run.evaluation.passed  # ...but the task failed


async def test_failed_run_is_still_evaluated(settings: Settings) -> None:
    turns = [{"tool_calls": [{"name": "list_directory", "arguments": {}}]}] * 5
    run = await run_agent(
        scripted_config(turns, limits=RunLimits(max_steps=2)),
        "g",
        settings=settings,
        evaluators=[EvaluatorSpec(type="completed")],
    )
    assert run.status == RunStatus.FAILED
    assert run.evaluation is not None and not run.evaluation.passed


async def test_consecutive_tool_errors_abort(settings: Settings) -> None:
    turns = [{"tool_calls": [{"name": "read_file", "arguments": {"path": "nope"}}]}] * 10
    config = scripted_config(turns, limits=RunLimits(max_consecutive_tool_errors=3))
    run = await run_agent(config, "g", settings=settings)
    assert run.status == RunStatus.FAILED
    assert run.error is not None and run.error.type == "tool_errors"
    assert run.metrics.tool_errors == 3 and run.metrics.tool_success_rate == 0.0


async def test_tool_call_budget(settings: Settings) -> None:
    turns = [
        {"tool_calls": [{"name": "list_directory", "arguments": {}}] * 3},
        {"text": "done"},
    ]
    run = await run_agent(
        scripted_config(turns, limits=RunLimits(max_tool_calls=2)), "g", settings=settings
    )
    statuses = [c.status for c in run.steps[0].tool_calls]
    assert statuses == [ToolCallStatus.SUCCESS, ToolCallStatus.SUCCESS, ToolCallStatus.DENIED]


async def test_plan_execute_strategy_records_plan(settings: Settings) -> None:
    turns = [{"text": "1. Inspect files\n2. Write output\n3. Verify"}, *write_turns()]
    config = scripted_config(turns, planner=PlannerConfig(strategy=PlannerStrategy.PLAN_EXECUTE))
    run = await run_agent(config, "g", settings=settings)
    assert run.status == RunStatus.SUCCEEDED
    assert run.plan == ["Inspect files", "Write output", "Verify"]
    assert run.steps[0].kind == StepKind.PLAN


class CapturingProvider(LLMProvider):
    name = "capture"

    def __init__(self, stop: StopReason = StopReason.END_TURN) -> None:
        self.requests: list[CompletionRequest] = []
        self.stop = stop

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content=[])
            if self.stop == StopReason.REFUSAL
            else Message.assistant("final"),
            stop_reason=self.stop,
            model="m",
        )


async def test_memory_recall_injected_and_summary_persisted(settings: Settings) -> None:
    store = InMemoryMemoryStore()
    await store.add(
        MemoryRecord(
            scope=MemoryScope.AGENT, namespace="agt_1", content="Deployment uses make deploy"
        )
    )
    provider = CapturingProvider()
    config = scripted_config([], memory={"persist": True})
    prepared = prepare_run(
        config,
        "how do I run deployment?",
        agent_id="agt_1",
        settings=settings,
        memory=store,
        provider=provider,
    )
    run = await prepared.execute()
    assert "Deployment uses make deploy" in (provider.requests[0].system or "")
    records = await store.list_records(MemoryScope.AGENT, "agt_1")
    assert len(records) == 2 and "Outcome: succeeded" in records[0].content
    assert run.status == RunStatus.SUCCEEDED


async def test_refusal_fails_run(settings: Settings) -> None:
    prepared = prepare_run(
        scripted_config([]), "g", settings=settings, provider=CapturingProvider(StopReason.REFUSAL)
    )
    run = await prepared.execute()
    assert run.status == RunStatus.FAILED
    assert run.error is not None and run.error.type == "llm.refusal"


async def test_observer_failure_does_not_break_run(settings: Settings) -> None:
    class Broken:
        async def on_event(self, event: RunEvent, run: Any) -> None:
            raise RuntimeError("observer bug")

    run = await run_agent(
        scripted_config(write_turns()), "g", settings=settings, observers=[Broken()]
    )
    assert run.status == RunStatus.SUCCEEDED


async def test_unknown_tool_reported_to_model(settings: Settings) -> None:
    turns = [{"tool_calls": [{"name": "does_not_exist", "arguments": {}}]}, {"text": "ok"}]
    run = await run_agent(scripted_config(turns), "g", settings=settings)
    assert run.steps[0].tool_calls[0].status == ToolCallStatus.INVALID_INPUT
    assert run.status == RunStatus.SUCCEEDED


async def test_llm_error_type_from_provider_code(settings: Settings) -> None:
    class Failing(LLMProvider):
        name = "failing"

        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            raise LLMError("nope", retryable=False, code="authentication")

    run = await prepare_run(
        scripted_config([]), "g", settings=settings, provider=Failing()
    ).execute()
    assert run.error is not None and run.error.type == "llm.authentication"


async def test_broadcaster_end_marker_survives_full_queue() -> None:
    """Regression: a full subscriber queue dropped the end-of-stream marker."""
    from agentforge.runtime.events import EventBroadcaster

    broadcaster = EventBroadcaster(max_queue=2)
    run = type("R", (), {"id": "run_x"})()
    queue = broadcaster.subscribe("run_x")
    for i in range(5):
        await broadcaster.on_event(RunEvent(run_id="run_x", type=f"step.{i}"), run)
    await broadcaster.on_event(RunEvent(run_id="run_x", type="run.finished"), run)
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert items[-1] is None


class TokenHungryProvider(LLMProvider):
    """Keeps asking for a tool call and reports 400 tokens per turn."""

    name = "hungry"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        from agentforge.core.models import TokenUsage
        from agentforge.llm.types import ToolUsePart

        turn = sum(1 for m in request.messages if m.role == Role.ASSISTANT)
        return CompletionResponse(
            message=Message(
                role=Role.ASSISTANT,
                content=[ToolUsePart(id=f"c{turn}", name="list_directory", arguments={})],
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=TokenUsage(input_tokens=300, output_tokens=100),
            model="m",
        )


async def test_token_budget_stops_the_run(settings: Settings) -> None:
    config = scripted_config([], limits=RunLimits(max_steps=20, max_total_tokens=1_000))
    prepared = prepare_run(config, "g", settings=settings, provider=TokenHungryProvider())
    run = await prepared.execute()
    assert run.status == RunStatus.FAILED
    assert run.error is not None and run.error.type == "token_budget"
    assert run.usage.total_tokens == 1_200  # stopped after the 3rd call (>= 1000)
    assert len(run.steps) == 3
    # Default: no budget, so the same provider runs until the step limit.
    unlimited = scripted_config([], limits=RunLimits(max_steps=4))
    run = await prepare_run(
        unlimited, "g", settings=settings, provider=TokenHungryProvider()
    ).execute()
    assert run.error is not None and run.error.type == "max_steps"
