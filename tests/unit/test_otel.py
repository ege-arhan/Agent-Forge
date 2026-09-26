from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agentforge.evaluation.base import EvaluatorSpec
from agentforge.observability.otel import OpenTelemetryObserver
from agentforge.runtime.factory import run_agent
from agentforge.settings import Settings
from tests.conftest import scripted_config


async def test_finished_run_exported_as_trace(settings: Settings) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    observer = OpenTelemetryObserver(provider.get_tracer("test"))
    turns = [
        {
            "tool_calls": [
                {
                    "name": "write_file",
                    "arguments": {"path": "a.txt", "content": "super-secret-value"},
                },
                {"name": "read_file", "arguments": {"path": "missing.txt"}},
            ]
        },
        {"text": "done"},
    ]
    run = await run_agent(
        scripted_config(turns),
        "write a file",
        settings=settings,
        observers=[observer],
        evaluators=[EvaluatorSpec(type="file_exists", path="a.txt")],
    )
    spans = {s.name: s for s in exporter.get_finished_spans()}
    names = [s.name for s in exporter.get_finished_spans()]
    assert names.count("agentforge.step") == 3  # two actions + evaluation
    root = spans["agentforge.run"]
    assert root.attributes["agentforge.run.id"] == run.id
    assert root.attributes["agentforge.evaluation.passed"] is True
    assert root.parent is None

    chat = next(s for s in exporter.get_finished_spans() if s.name.startswith("chat "))
    assert chat.attributes["gen_ai.operation.name"] == "chat"
    assert chat.attributes["gen_ai.system"] == "scripted"

    tools = [s for s in exporter.get_finished_spans() if s.name.startswith("execute_tool")]
    assert {s.attributes["gen_ai.tool.name"] for s in tools} == {"write_file", "read_file"}
    failed = next(s for s in tools if s.attributes["gen_ai.tool.name"] == "read_file")
    assert failed.status.status_code == StatusCode.ERROR
    # parent chain: tool -> step -> run, all in one trace
    step_ids = {
        s.context.span_id for s in exporter.get_finished_spans() if s.name == "agentforge.step"
    }
    assert all(t.parent is not None and t.parent.span_id in step_ids for t in tools)
    assert len({s.context.trace_id for s in exporter.get_finished_spans()}) == 1
    # timings come from the record
    assert root.start_time <= chat.start_time <= chat.end_time <= root.end_time
    # arguments/outputs are never exported
    dump = str([dict(s.attributes or {}) for s in exporter.get_finished_spans()])
    assert "super-secret-value" not in dump
