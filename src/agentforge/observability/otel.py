"""OpenTelemetry trace export (optional ``agentforge[otel]`` extra).

When a run finishes, its complete record is converted into a trace:

```
agentforge.run            (run span: goal, agent, status, evaluation)
├── agentforge.step       (one per step)
│   ├── chat <model>      (LLM call: GenAI semantic-convention attributes)
│   └── execute_tool <t>  (one per tool call)
└── ...
```

Spans are created *after* the fact with the timestamps recorded by the
runtime, so exported timings are exact and tracing adds no overhead or failure
modes to the agent loop itself. Live progress remains available through the
run event stream (SSE).

Attributes follow the OpenTelemetry GenAI semantic conventions where they
exist (``gen_ai.*``); AgentForge-specific attributes use ``agentforge.*``.
Tool arguments and outputs are *not* exported (they may contain sensitive
data); only names, statuses and durations are.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentforge.core.models import Run, Step
from agentforge.runtime.events import RunEvent

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

logger = logging.getLogger("agentforge.otel")

TRACER_NAME = "agentforge"


def _ns(value: datetime | None) -> int | None:
    return int(value.timestamp() * 1_000_000_000) if value is not None else None


def _set(span: Any, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def export_run(run: Run, tracer: Tracer) -> None:
    """Emit the trace for a finished run."""
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    start = _ns(run.started_at) or _ns(run.created_at)
    end = _ns(run.finished_at) or start
    run_span = tracer.start_span("agentforge.run", start_time=start)
    _set(
        run_span,
        {
            "agentforge.run.id": run.id,
            "agentforge.agent.name": run.agent_name,
            "agentforge.agent.id": run.agent_id,
            "agentforge.run.status": run.status.value,
            "agentforge.run.goal": run.goal[:1_000],
            "agentforge.run.steps": run.metrics.steps,
            "agentforge.run.tool_calls": run.metrics.tool_calls,
            "agentforge.planner": run.config.planner.strategy.value,
            "agentforge.sandbox": run.config.sandbox.kind.value,
            "gen_ai.system": run.config.model.provider,
            "gen_ai.request.model": run.config.model.model or None,
            "gen_ai.usage.input_tokens": run.usage.input_tokens,
            "gen_ai.usage.output_tokens": run.usage.output_tokens,
            "agentforge.cost_usd": run.metrics.cost_usd,
            "agentforge.evaluation.passed": run.evaluation.passed if run.evaluation else None,
            "agentforge.evaluation.score": run.evaluation.score if run.evaluation else None,
        },
    )
    for key, value in run.labels.items():
        run_span.set_attribute(f"agentforge.label.{key}", value)
    if run.error is not None:
        run_span.set_status(Status(StatusCode.ERROR, f"{run.error.type}: {run.error.message}"))

    context = trace.set_span_in_context(run_span)
    for step in run.steps:
        _export_step(step, tracer, context, run)
    run_span.end(end_time=end)


def _export_step(step: Step, tracer: Tracer, context: Any, run: Run) -> None:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    start = _ns(step.started_at)
    end = _ns(step.finished_at) or _ns(run.finished_at) or start
    span = tracer.start_span("agentforge.step", context=context, start_time=start)
    _set(
        span,
        {
            "agentforge.step.index": step.index,
            "agentforge.step.kind": step.kind.value,
            "agentforge.evaluation.passed": step.evaluation.passed if step.evaluation else None,
            "agentforge.evaluation.score": step.evaluation.score if step.evaluation else None,
        },
    )
    if step.error is not None:
        span.set_status(Status(StatusCode.ERROR, step.error.message))
    step_context = trace.set_span_in_context(span)

    llm = step.llm_call
    if llm is not None:
        llm_span = tracer.start_span(
            f"chat {llm.model}", context=step_context, start_time=_ns(llm.started_at)
        )
        _set(
            llm_span,
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.system": llm.provider,
                "gen_ai.request.model": llm.model,
                "gen_ai.response.finish_reasons": [llm.stop_reason] if llm.stop_reason else None,
                "gen_ai.usage.input_tokens": llm.usage.input_tokens,
                "gen_ai.usage.output_tokens": llm.usage.output_tokens,
                "agentforge.llm.attempts": llm.attempts,
                "agentforge.cost_usd": llm.cost_usd,
            },
        )
        if llm.error is not None:
            llm_span.set_status(Status(StatusCode.ERROR, llm.error.message))
        llm_span.end(end_time=_ns(llm.finished_at))

    for call in step.tool_calls:
        tool_span = tracer.start_span(
            f"execute_tool {call.tool}", context=step_context, start_time=_ns(call.started_at)
        )
        _set(
            tool_span,
            {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": call.tool,
                "gen_ai.tool.call.id": call.id,
                "agentforge.tool.status": call.status.value,
                "agentforge.tool.duration_ms": call.duration_ms,
                "agentforge.tool.truncated": call.truncated,
            },
        )
        if call.status.value != "success":
            tool_span.set_status(Status(StatusCode.ERROR, call.status.value))
        tool_span.end(end_time=_ns(call.finished_at))
    span.end(end_time=end)


class OpenTelemetryObserver:
    """Run observer that exports each finished run as a trace."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        if tracer is None:
            from opentelemetry import trace

            tracer = trace.get_tracer(TRACER_NAME)
        self._tracer = tracer

    async def on_event(self, event: RunEvent, run: Run) -> None:
        if event.type == "run.finished":
            export_run(run, self._tracer)


def configure_tracing(service_name: str = "agentforge") -> OpenTelemetryObserver:
    """Install an SDK tracer provider exporting via OTLP/HTTP.

    The exporter honours the standard ``OTEL_EXPORTER_OTLP_*`` environment
    variables (endpoint, headers). Requires ``pip install 'agentforge[otel]'``.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        from agentforge.core.errors import ConfigurationError

        raise ConfigurationError(
            "OpenTelemetry export requires: pip install 'agentforge[otel]'"
        ) from exc

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry tracing enabled (OTLP/HTTP)")
    return OpenTelemetryObserver(provider.get_tracer(TRACER_NAME))
