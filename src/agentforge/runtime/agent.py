"""The agent runtime: goal -> plan -> act/observe loop -> evaluate -> finish.

One :class:`AgentRuntime` executes one run. Dependencies (provider, tools,
sandbox, memory, observers) are injected so the runtime can be tested with
fakes and assembled differently by the CLI, API server and benchmark engine
(see :mod:`agentforge.runtime.factory`).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from agentforge.core.config import AgentConfig
from agentforge.core.errors import LLMError, RunCancelledError
from agentforge.core.ids import utcnow
from agentforge.core.models import (
    ErrorInfo,
    EvaluationResult,
    LLMCallRecord,
    Run,
    RunStatus,
    Step,
    StepKind,
    ToolCallRecord,
    ToolCallStatus,
)
from agentforge.evaluation.base import EvaluationContext, EvaluatorSpec, evaluate
from agentforge.evaluation.metrics import compute_metrics
from agentforge.llm.base import LLMProvider
from agentforge.llm.pricing import PriceTable
from agentforge.llm.types import (
    CompletionRequest,
    CompletionResponse,
    ContentPart,
    Message,
    Role,
    StopReason,
    ToolResultPart,
    ToolUsePart,
)
from agentforge.memory.base import MemoryRecord, MemoryScope, MemoryStore
from agentforge.memory.context import compact_history
from agentforge.observability.redaction import Redactor
from agentforge.runtime.approval import ApprovalGate
from agentforge.runtime.events import RunEvent, RunObserver, notify
from agentforge.runtime.planner import build_plan_request, parse_plan, plan_section
from agentforge.sandbox.base import Sandbox
from agentforge.sandbox.workspace import Workspace
from agentforge.tools.base import Permission
from agentforge.tools.executor import ToolExecutor

logger = logging.getLogger("agentforge.runtime")

EVALUATION_TIMEOUT_SECONDS = 900.0


class _RunTerminatedError(Exception):
    """Internal: terminate the loop with a given status and error."""

    def __init__(self, status: RunStatus, error: ErrorInfo) -> None:
        super().__init__(error.message)
        self.status = status
        self.error = error


@dataclass
class RuntimeDeps:
    provider: LLMProvider
    executor: ToolExecutor
    workspace: Workspace
    sandbox: Sandbox
    memory: MemoryStore | None = None
    observers: list[RunObserver] = field(default_factory=list)
    price_table: PriceTable = field(default_factory=PriceTable)
    redactor: Redactor = field(default_factory=Redactor)
    env: dict[str, str] = field(default_factory=dict)


class AgentRuntime:
    def __init__(self, config: AgentConfig, deps: RuntimeDeps) -> None:
        self.config = config
        self.deps = deps
        self._cancel = asyncio.Event()
        self.approval = ApprovalGate()
        self._approval_permissions = frozenset(Permission(p) for p in config.approval.require_for)

    # ------------------------------------------------------------------ control
    def cancel(self) -> None:
        """Request cooperative cancellation (checked between steps and tool calls)."""
        self._cancel.set()

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise RunCancelledError("run cancelled")

    async def _emit(self, run: Run, type_: str, **data: object) -> None:
        await notify(self.deps.observers, RunEvent(run_id=run.id, type=type_, data=data), run)

    # --------------------------------------------------------------- entrypoint
    async def execute(self, run: Run, evaluators: list[EvaluatorSpec] | None = None) -> Run:
        """Execute ``run`` to completion and return the updated record.

        Never raises for agent-level failures: they are recorded on the run.
        Re-raises ``asyncio.CancelledError`` after recording cancellation.
        """
        evaluators = evaluators or []
        run.evaluators = [spec.model_dump(mode="json") for spec in evaluators]
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        run.workspace = str(self.deps.workspace.root)
        await self._emit(run, "run.started", goal=run.goal, agent=run.agent_name)

        hard_cancelled = False
        try:
            async with asyncio.timeout(self.config.limits.timeout_seconds):
                await self.deps.sandbox.start()
                await self._loop(run, evaluators)
            run.status = RunStatus.SUCCEEDED
        except _RunTerminatedError as stop:
            run.status, run.error = stop.status, stop.error
        except RunCancelledError:
            run.status = RunStatus.CANCELLED
            run.error = ErrorInfo(type="cancelled", message="run cancelled by user")
        except TimeoutError:
            run.status = RunStatus.TIMED_OUT
            run.error = ErrorInfo(
                type="timeout",
                message=f"run exceeded {self.config.limits.timeout_seconds:g}s timeout",
            )
        except asyncio.CancelledError:
            hard_cancelled = True
            run.status = RunStatus.CANCELLED
            run.error = ErrorInfo(type="cancelled", message="run task cancelled")
        except LLMError as exc:
            run.status = RunStatus.FAILED
            run.error = ErrorInfo(
                type=f"llm.{exc.code}", message=exc.message, retryable=exc.retryable
            )
        except Exception as exc:
            logger.exception("run %s crashed", run.id)
            run.status = RunStatus.FAILED
            run.error = ErrorInfo(type="internal", message=f"{type(exc).__name__}: {exc}")

        # Finalisation must complete even if the surrounding task is cancelled.
        await asyncio.shield(self._finalize(run, evaluators))
        if hard_cancelled:
            raise asyncio.CancelledError
        return run

    async def _finalize(self, run: Run, evaluators: list[EvaluatorSpec]) -> None:
        try:
            if evaluators and run.evaluation is None and run.status != RunStatus.CANCELLED:
                # Post-mortem evaluation so failed runs still get scored.
                try:
                    async with asyncio.timeout(EVALUATION_TIMEOUT_SECONDS):
                        run.evaluation = await self._evaluate(run, evaluators)
                except TimeoutError:
                    logger.warning("evaluation of run %s timed out", run.id)
        finally:
            try:
                await self.deps.sandbox.close()
            except Exception:
                logger.exception("failed to close sandbox for run %s", run.id)
            run.finished_at = utcnow()
            run.metrics = compute_metrics(run)
            await self._persist_memory(run)
            await self._emit(
                run,
                "run.finished",
                status=run.status.value,
                error=run.error.message if run.error else None,
                passed=run.evaluation.passed if run.evaluation else None,
            )

    # --------------------------------------------------------------------- loop
    async def _loop(self, run: Run, evaluators: list[EvaluatorSpec]) -> None:
        config = self.config
        limits = config.limits
        tool_names = [spec.name for spec in self.deps.executor.specs]

        memories = await self._recall(run)
        plan = await self._plan(run, tool_names)
        system = self._system_prompt(memories, plan)

        messages: list[Message] = [Message.user(run.goal)]
        evaluation_attempts = 0
        consecutive_error_steps = 0
        total_tool_calls = 0

        for _ in range(limits.max_steps):
            self._check_cancelled()
            step = Step(index=len(run.steps), kind=StepKind.ACTION)
            run.steps.append(step)
            await self._emit(run, "step.started", step=step.index)

            request = CompletionRequest(
                model=config.model.model,
                system=system,
                messages=compact_history(messages, config.memory.keep_recent_messages),
                tools=self.deps.executor.specs,
                max_tokens=config.model.max_tokens,
                temperature=config.model.temperature,
                session_id=run.id,
            )
            try:
                response = await self._complete(run, step, request)
            except LLMError as exc:
                step.error = ErrorInfo(
                    type=f"llm.{exc.code}", message=exc.message, retryable=exc.retryable
                )
                step.finished_at = utcnow()
                await self._emit(run, "step.finished", step=step.index, error=exc.message)
                raise

            budget = limits.max_total_tokens
            if budget is not None and run.usage.total_tokens >= budget:
                step.thought = response.message.text
                step.finished_at = utcnow()
                await self._emit(run, "step.finished", step=step.index)
                raise _RunTerminatedError(
                    RunStatus.FAILED,
                    ErrorInfo(
                        type="token_budget",
                        message=f"stopped after {run.usage.total_tokens} tokens (budget {budget})",
                    ),
                )

            step.thought = response.message.text
            messages.append(response.message)
            tool_uses = response.message.tool_uses

            if tool_uses:
                results: list[ContentPart] = []
                for call in tool_uses:
                    self._check_cancelled()
                    if total_tool_calls >= limits.max_tool_calls:
                        record, result = self._budget_exhausted(call.id, call.name)
                    else:
                        total_tool_calls += 1
                        required = self._approval_permissions & self.deps.executor.permissions_for(
                            call.name
                        )
                        if required:
                            record, result = await self._execute_with_approval(
                                run, step, call, required
                            )
                        else:
                            record, result = await self.deps.executor.execute(call)
                    step.tool_calls.append(record)
                    results.append(result)
                    await self._emit(
                        run,
                        "tool.finished",
                        step=step.index,
                        tool=record.tool,
                        status=record.status.value,
                        duration_ms=record.duration_ms,
                    )
                messages.append(Message(role=Role.USER, content=results))
                step.finished_at = utcnow()
                await self._emit(run, "step.finished", step=step.index)

                if all(c.status != ToolCallStatus.SUCCESS for c in step.tool_calls):
                    consecutive_error_steps += 1
                else:
                    consecutive_error_steps = 0
                if consecutive_error_steps >= limits.max_consecutive_tool_errors:
                    raise _RunTerminatedError(
                        RunStatus.FAILED,
                        ErrorInfo(
                            type="tool_errors",
                            message=f"{consecutive_error_steps} consecutive steps with only "
                            "failing tool calls",
                        ),
                    )
                continue

            step.finished_at = utcnow()
            await self._emit(run, "step.finished", step=step.index)

            if response.stop_reason == StopReason.REFUSAL:
                raise _RunTerminatedError(
                    RunStatus.FAILED,
                    ErrorInfo(type="llm.refusal", message="the model declined the request"),
                )
            if response.stop_reason == StopReason.MAX_TOKENS:
                messages.append(
                    Message.user("Your last response was cut off by the output limit. Continue.")
                )
                continue

            run.result = response.message.text
            if not evaluators:
                return
            evaluation = await self._evaluate(run, evaluators)
            run.evaluation = evaluation
            if evaluation.passed or evaluation_attempts >= config.retry.evaluation_retries:
                return
            evaluation_attempts += 1
            run.result = None
            run.evaluation = None
            messages.append(
                Message.user(
                    "Your work was checked and did not pass yet:\n"
                    f"{evaluation.feedback()}\n"
                    "Continue working to fix these problems, then give your final answer."
                )
            )

        raise _RunTerminatedError(
            RunStatus.FAILED,
            ErrorInfo(type="max_steps", message=f"reached the limit of {limits.max_steps} steps"),
        )

    # ------------------------------------------------------------------ helpers
    def _budget_exhausted(self, call_id: str, tool: str) -> tuple[ToolCallRecord, ToolResultPart]:
        now = utcnow()
        message = "tool call budget exhausted; finish with the information you have"
        record = ToolCallRecord(
            id=call_id,
            tool=tool,
            status=ToolCallStatus.DENIED,
            output=message,
            error=message,
            started_at=now,
            finished_at=now,
            duration_ms=0,
        )
        return record, ToolResultPart(tool_use_id=call_id, content=message, is_error=True)

    async def _execute_with_approval(
        self, run: Run, step: Step, call: ToolUsePart, permissions: frozenset[Permission]
    ) -> tuple[ToolCallRecord, ToolResultPart]:
        previous_status = run.status
        run.status = RunStatus.AWAITING_APPROVAL
        permission_values = frozenset(p.value for p in permissions)
        # Register before emitting: an observer (e.g. the non-interactive CLI) may
        # call decide() synchronously while handling the event, before we start
        # waiting below, and that decision must not be lost.
        self.approval.begin(call.id, call.name, call.arguments, permission_values)
        await self._emit(
            run,
            "tool.awaiting_approval",
            step=step.index,
            tool=call.name,
            call_id=call.id,
            arguments=self.deps.redactor.redact(call.arguments),
            permissions=sorted(permission_values),
        )
        approved, reason = await self.approval.wait(
            call.id, timeout=self.config.approval.timeout_seconds, cancel_event=self._cancel
        )
        run.status = previous_status
        if approved:
            await self._emit(run, "tool.approved", step=step.index, tool=call.name, call_id=call.id)
            return await self.deps.executor.execute(call)
        await self._emit(
            run, "tool.denied", step=step.index, tool=call.name, call_id=call.id, reason=reason
        )
        return self._approval_denied(call.id, call.name, reason)

    def _approval_denied(
        self, call_id: str, tool: str, reason: str | None
    ) -> tuple[ToolCallRecord, ToolResultPart]:
        now = utcnow()
        message = f"tool call denied: {reason or 'not approved'}"
        record = ToolCallRecord(
            id=call_id,
            tool=tool,
            status=ToolCallStatus.DENIED,
            output=message,
            error=message,
            started_at=now,
            finished_at=now,
            duration_ms=0,
        )
        return record, ToolResultPart(tool_use_id=call_id, content=message, is_error=True)

    async def _complete(
        self, run: Run, step: Step, request: CompletionRequest
    ) -> CompletionResponse:
        policy = self.config.retry
        model = self.config.model
        started_at = utcnow()
        t0 = time.monotonic()
        attempt = 0
        while True:
            attempt += 1
            self._check_cancelled()
            try:
                response = await self.deps.provider.complete(request)
                break
            except LLMError as exc:
                if not exc.retryable or attempt >= policy.llm_max_attempts:
                    step.llm_call = LLMCallRecord(
                        provider=model.provider,
                        model=request.model,
                        started_at=started_at,
                        finished_at=utcnow(),
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        attempts=attempt,
                        error=ErrorInfo(
                            type=f"llm.{exc.code}", message=exc.message, retryable=exc.retryable
                        ),
                    )
                    raise
                delay = min(
                    policy.backoff_max_seconds,
                    policy.backoff_initial_seconds * policy.backoff_multiplier ** (attempt - 1),
                )
                delay *= random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not crypto
                await self._emit(
                    run,
                    "llm.retry",
                    step=step.index,
                    attempt=attempt,
                    error=exc.message,
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)

        cost = self.deps.price_table.estimate(model.provider, response.model, response.usage)
        if cost is None and response.model != request.model and request.model:
            cost = self.deps.price_table.estimate(model.provider, request.model, response.usage)
        step.llm_call = LLMCallRecord(
            provider=model.provider,
            model=response.model,
            started_at=started_at,
            finished_at=utcnow(),
            latency_ms=int((time.monotonic() - t0) * 1000),
            attempts=attempt,
            stop_reason=response.raw_stop_reason or response.stop_reason.value,
            usage=response.usage,
            cost_usd=cost,
        )
        run.usage.add(response.usage)
        await self._emit(
            run,
            "llm.finished",
            step=step.index,
            attempts=attempt,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason.value,
        )
        return response

    async def _plan(self, run: Run, tool_names: list[str]) -> list[str] | None:
        plan_request = build_plan_request(self.config.planner, run.goal, tool_names)
        if plan_request is None:
            return None
        step = Step(index=len(run.steps), kind=StepKind.PLAN)
        run.steps.append(step)
        request = CompletionRequest(
            model=self.config.model.model,
            system=self.config.system_prompt,
            messages=[plan_request.prompt],
            max_tokens=min(self.config.model.max_tokens, 2_048),
            temperature=self.config.model.temperature,
            session_id=run.id,
        )
        response = await self._complete(run, step, request)
        plan = parse_plan(response, self.config.planner.max_plan_steps)
        step.plan = plan
        step.thought = response.message.text
        step.finished_at = utcnow()
        run.plan = plan
        await self._emit(run, "plan.created", steps=len(plan))
        return plan

    def _system_prompt(self, memories: list[str], plan: list[str] | None) -> str:
        sections = [self.config.system_prompt.strip()]
        sections.append(
            "# Environment\n"
            "You work inside an isolated workspace directory; all file paths are relative to "
            "it. Use the provided tools to act and observe results. When the goal is achieved, "
            "reply with a final answer that summarises what you did, without calling tools."
        )
        if memories:
            sections.append(
                "# Relevant notes from previous runs\n" + "\n".join(f"- {m}" for m in memories)
            )
        if plan:
            sections.append(plan_section(plan))
        return "\n\n".join(sections)

    async def _recall(self, run: Run) -> list[str]:
        memory_cfg = self.config.memory
        store = self.deps.memory
        if (
            store is None
            or not memory_cfg.enabled
            or not run.agent_id
            or memory_cfg.recall_limit == 0
        ):
            return []
        hits = await store.search(
            MemoryScope.AGENT, run.agent_id, run.goal, limit=memory_cfg.recall_limit
        )
        return [hit.record.content for hit in hits]

    async def _persist_memory(self, run: Run) -> None:
        store = self.deps.memory
        if store is None or not self.config.memory.persist or not run.agent_id:
            return
        outcome = run.status.value
        if run.evaluation is not None:
            outcome += f"; evaluation {'passed' if run.evaluation.passed else 'failed'}"
            outcome += f" (score {run.evaluation.score:.2f})"
        summary = f"Goal: {run.goal[:500]}\nOutcome: {outcome}"
        if run.result:
            summary += f"\nResult: {run.result[:1_000]}"
        if run.error:
            summary += f"\nError: {run.error.message[:300]}"
        try:
            await store.add(
                MemoryRecord(
                    scope=MemoryScope.AGENT,
                    namespace=run.agent_id,
                    content=self.deps.redactor.redact_text(summary),
                    tags=["run-summary", run.status.value],
                    metadata={"run_id": run.id},
                )
            )
        except Exception:
            logger.exception("failed to persist memory for run %s", run.id)

    async def _evaluate(self, run: Run, evaluators: list[EvaluatorSpec]) -> EvaluationResult:
        step = Step(index=len(run.steps), kind=StepKind.EVALUATION)
        run.steps.append(step)
        ctx = EvaluationContext(
            run=run, workspace=self.deps.workspace, sandbox=self.deps.sandbox, env=self.deps.env
        )
        result = await evaluate(evaluators, ctx)
        if result is None:  # pragma: no cover - evaluators is non-empty
            raise RuntimeError("evaluation produced no result")
        step.evaluation = result
        step.finished_at = utcnow()
        await self._emit(
            run, "evaluation.finished", step=step.index, passed=result.passed, score=result.score
        )
        return result
