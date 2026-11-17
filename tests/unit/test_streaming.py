"""Tests for LLM streaming support (T-003b).

Covers: CompletionStream base class, Anthropic streaming, OpenAI-compatible
streaming, runtime _stream_completion integration, ConsoleObserver llm.delta
handling, and scripted provider's default stream() fallback.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock

import httpx2
import openai
import pytest

from agentforge.cli import ConsoleObserver
from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.core.models import Run, Step, StepKind, TokenUsage
from agentforge.llm.anthropic import AnthropicProvider
from agentforge.llm.base import LLMProvider
from agentforge.llm.openai_compat import PRESETS, OpenAICompatibleProvider
from agentforge.llm.scripted import ScriptedProvider
from agentforge.llm.types import (
    CompletionRequest,
    CompletionResponse,
    CompletionStream,
    Message,
    StopReason,
    StreamDelta,
)
from agentforge.runtime.events import RunEvent


# ----------------------------------------------------------------- helpers
def _simple_request(model: str = "test-model") -> CompletionRequest:
    return CompletionRequest(model=model, messages=[Message.user("hello")], max_tokens=100)


# ===================================================================
#  CompletionStream base class
# ===================================================================


async def test_completion_stream_base_wraps_response() -> None:
    response = CompletionResponse(
        message=Message.assistant("hello"),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        model="test",
    )
    stream = CompletionStream(response)
    chunks: list[StreamDelta] = []
    async for delta in stream:
        chunks.append(delta)
    assert chunks == []
    assert stream.response is response


async def test_completion_stream_base_no_response_raises() -> None:
    stream = CompletionStream()
    async for _ in stream:
        pass
    with pytest.raises(RuntimeError, match="not yet exhausted"):
        _ = stream.response


# ===================================================================
#  Anthropic streaming
# ===================================================================


class _FakeAnthropicTextStream:
    """Mimics the Anthropic SDK text_stream async iterator."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self._index = 0

    def __aiter__(self) -> _FakeAnthropicTextStream:
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        text = self._chunks[self._index]
        self._index += 1
        return text


class _FakeAnthropicStreamCtx:
    """Mimics the entered stream context manager (has text_stream, get_final_message)."""

    def __init__(self, chunks: list[str], final_message: Any) -> None:
        self.text_stream = _FakeAnthropicTextStream(chunks)
        self._final = final_message

    async def get_final_message(self) -> Any:
        return self._final


class _FakeAnthropicStreamCM:
    """Mimics the return value of client.messages.stream() (async context manager)."""

    def __init__(self, ctx: _FakeAnthropicStreamCtx) -> None:
        self._ctx = ctx

    async def __aenter__(self) -> _FakeAnthropicStreamCtx:
        return self._ctx

    async def __aexit__(self, *args: Any) -> None:
        pass


def _make_anthropic_final(
    text: str = "Hello world",
    model: str = "claude-opus-5",
    input_tokens: int = 50,
    output_tokens: int = 10,
) -> MagicMock:
    final = MagicMock()
    final.content = [MagicMock()]
    final.content[0].model_dump.return_value = {"type": "text", "text": text}
    final.stop_reason = "end_turn"
    final.model = model
    final.id = "msg_stream_1"
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    final.usage = usage
    return final


async def test_anthropic_stream_yields_deltas_and_response() -> None:
    chunks = ["Hello", " ", "world"]
    final = _make_anthropic_final("Hello world")
    ctx = _FakeAnthropicStreamCtx(chunks, final)
    cm = _FakeAnthropicStreamCM(ctx)

    client = MagicMock()
    client.messages.stream.return_value = cm
    provider = AnthropicProvider(client=client)

    stream = await provider.stream(_simple_request("claude-opus-5"))
    deltas: list[str] = []
    async for delta in stream:
        deltas.append(delta.text)

    assert deltas == ["Hello", " ", "world"]
    resp = stream.response
    assert resp.message.text == "Hello world"
    assert resp.stop_reason == StopReason.END_TURN
    assert resp.usage.input_tokens == 50
    assert resp.usage.output_tokens == 10
    assert resp.model == "claude-opus-5"
    assert resp.response_id == "msg_stream_1"


async def test_anthropic_stream_empty() -> None:
    final = _make_anthropic_final("", model="claude-opus-5")
    ctx = _FakeAnthropicStreamCtx([], final)
    cm = _FakeAnthropicStreamCM(ctx)

    client = MagicMock()
    client.messages.stream.return_value = cm
    provider = AnthropicProvider(client=client)

    stream = await provider.stream(_simple_request("claude-opus-5"))
    deltas: list[str] = []
    async for delta in stream:
        deltas.append(delta.text)
    assert deltas == []
    assert stream.response.model == "claude-opus-5"


# ===================================================================
#  OpenAI-compatible streaming
# ===================================================================


def _openai_sse_handler(
    chunks: list[dict[str, Any]],
) -> Any:
    """Build a mock HTTP handler that returns Server-Sent Events for the OpenAI SDK."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body.get("stream") is True
        lines: list[str] = []
        for chunk in chunks:
            lines.append(f"data: {json.dumps(chunk)}\n\n")
        lines.append("data: [DONE]\n\n")
        return httpx2.Response(
            200,
            content="".join(lines),
            headers={"content-type": "text/event-stream"},
        )

    return handler


def _openai_stream_chunks(
    text_parts: list[str],
    model: str = "gpt-test",
    finish_reason: str = "stop",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> list[dict[str, Any]]:
    """Build a list of SSE chunk payloads for a text-only response."""
    chunks: list[dict[str, Any]] = []
    for _i, text in enumerate(text_parts):
        chunks.append(
            {
                "id": "chatcmpl-s1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": text} if text else {"content": ""},
                        "finish_reason": None,
                    }
                ],
            }
        )
    # Final chunk with finish_reason and usage
    chunks.append(
        {
            "id": "chatcmpl-s1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }
    )
    return chunks


async def test_openai_stream_yields_text_deltas() -> None:
    chunks = _openai_stream_chunks(["Hello", " ", "world"])
    client = openai.AsyncOpenAI(
        api_key="test-key",
        base_url="http://openai.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(_openai_sse_handler(chunks))
        ),
    )
    provider = OpenAICompatibleProvider(PRESETS["openai"], client=client)
    stream = await provider.stream(_simple_request("gpt-test"))
    deltas: list[str] = []
    async for delta in stream:
        deltas.append(delta.text)

    assert deltas == ["Hello", " ", "world"]
    resp = stream.response
    assert resp.message.text == "Hello world"
    assert resp.stop_reason == StopReason.END_TURN
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 5
    assert resp.model == "gpt-test"


async def test_openai_stream_with_tool_calls() -> None:
    """Streaming with tool calls: arguments arrive in multiple chunks."""
    chunks = [
        {
            "id": "chatcmpl-tc",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"pa'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-tc",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": 'th": "x"}'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-tc",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
        },
    ]
    client = openai.AsyncOpenAI(
        api_key="test-key",
        base_url="http://openai.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(_openai_sse_handler(chunks))
        ),
    )
    provider = OpenAICompatibleProvider(PRESETS["openai"], client=client)
    stream = await provider.stream(_simple_request("gpt-test"))
    deltas: list[str] = []
    async for delta in stream:
        deltas.append(delta.text)

    assert deltas == []  # no text content, only tool calls
    resp = stream.response
    assert resp.stop_reason == StopReason.TOOL_USE
    assert len(resp.message.tool_uses) == 1
    tc = resp.message.tool_uses[0]
    assert tc.id == "call_1"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "x"}
    assert resp.usage.input_tokens == 20


async def test_openai_stream_responses_api_falls_back() -> None:
    """Responses API models fall back to the base stream() (wrapping complete())."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 0,
                "model": "grok-4.7",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "m1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "streamed via fallback"}],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            },
        )

    client = openai.AsyncOpenAI(
        api_key="test-key",
        base_url="http://openai.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    provider = OpenAICompatibleProvider(PRESETS["opencode-go"], client=client)
    stream = await provider.stream(_simple_request("grok-4.7"))
    # Responses API falls back: no deltas yielded, response available immediately
    deltas: list[str] = []
    async for delta in stream:
        deltas.append(delta.text)
    assert deltas == []
    assert stream.response.message.text == "streamed via fallback"


# ===================================================================
#  Scripted provider default stream()
# ===================================================================


async def test_scripted_stream_wraps_complete() -> None:
    provider = ScriptedProvider.from_options({"turns": [{"text": "scripted answer"}]})
    stream = await provider.stream(_simple_request())
    deltas: list[str] = []
    async for delta in stream:
        deltas.append(delta.text)
    assert deltas == []  # base wraps complete: no deltas
    assert stream.response.message.text == "scripted answer"


# ===================================================================
#  Runtime _stream_completion
# ===================================================================


class _FakeStreamProvider(LLMProvider):
    """Provider that yields controllable stream deltas."""

    name = "fake"

    def __init__(self, chunks: list[str], response: CompletionResponse) -> None:
        self._chunks = chunks
        self._response = response

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        return self._response

    async def stream(self, request: CompletionRequest) -> CompletionStream:
        return _FakeCompletionStream(self._chunks, self._response)


class _FakeCompletionStream(CompletionStream):
    def __init__(self, chunks: list[str], response: CompletionResponse) -> None:
        super().__init__()
        self._chunks = chunks
        self._final = response
        self._index = 0

    def __aiter__(self) -> _FakeCompletionStream:
        return self

    async def __anext__(self) -> StreamDelta:
        if self._index >= len(self._chunks):
            self._response = self._final
            raise StopAsyncIteration
        text = self._chunks[self._index]
        self._index += 1
        return StreamDelta(text=text)


async def test_runtime_stream_emits_delta_events() -> None:
    from agentforge.runtime.agent import AgentRuntime, RuntimeDeps
    from agentforge.sandbox.base import Sandbox
    from agentforge.sandbox.workspace import Workspace

    response = CompletionResponse(
        message=Message.assistant("Hello world"),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        model="fake-model",
    )
    provider = _FakeStreamProvider(["Hello", " ", "world"], response)

    events: list[RunEvent] = []

    class _Collector:
        async def on_event(self, event: RunEvent, run: Run) -> None:
            events.append(event)

    config = AgentConfig(
        name="test-stream",
        model=ModelConfig(provider="anthropic", stream=True),
        tools=[],
    )
    workspace = Workspace(root="/tmp/test-ws")
    executor = MagicMock()
    executor.specs = []
    deps = RuntimeDeps(
        provider=provider,
        executor=executor,
        workspace=workspace,
        sandbox=MagicMock(spec=Sandbox),
        observers=[_Collector()],
    )
    runtime = AgentRuntime(config, deps)
    run = Run(id="run_st", agent_name="test-stream", goal="test", config=config)
    step = Step(index=0, kind=StepKind.ACTION)
    request = _simple_request("fake-model")

    result = await runtime._stream_completion(run, step, request)

    delta_events = [e for e in events if e.type == "llm.delta"]
    assert len(delta_events) == 3
    assert delta_events[0].data["text"] == "Hello"
    assert delta_events[1].data["text"] == " "
    assert delta_events[2].data["text"] == "world"
    assert result is response


async def test_runtime_uses_stream_when_configured() -> None:
    """When model.stream=True and provider is in _STREAM_PROVIDERS, _complete uses streaming."""
    from agentforge.runtime.agent import _STREAM_PROVIDERS, AgentRuntime, RuntimeDeps
    from agentforge.sandbox.base import Sandbox
    from agentforge.sandbox.workspace import Workspace

    assert "anthropic" in _STREAM_PROVIDERS

    response = CompletionResponse(
        message=Message.assistant("streamed"),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=5, output_tokens=2),
        model="claude-opus-5",
    )
    provider = _FakeStreamProvider(["streamed"], response)

    events: list[RunEvent] = []

    class _Collector:
        async def on_event(self, event: RunEvent, run: Run) -> None:
            events.append(event)

    config = AgentConfig(
        name="test-stream-cfg",
        model=ModelConfig(provider="anthropic", stream=True),
        tools=[],
    )
    workspace = Workspace(root="/tmp/test-ws-cfg")
    executor = MagicMock()
    executor.specs = []
    deps = RuntimeDeps(
        provider=provider,
        executor=executor,
        workspace=workspace,
        sandbox=MagicMock(spec=Sandbox),
        observers=[_Collector()],
    )
    runtime = AgentRuntime(config, deps)
    run = Run(id="run_cfg", agent_name="test", goal="test", config=config)
    step = Step(index=0, kind=StepKind.ACTION)
    request = _simple_request("claude-opus-5")

    result = await runtime._complete(run, step, request)

    delta_events = [e for e in events if e.type == "llm.delta"]
    assert len(delta_events) == 1  # "streamed"
    finished = [e for e in events if e.type == "llm.finished"]
    assert len(finished) == 1
    assert result.message.text == "streamed"


async def test_runtime_skips_stream_when_disabled() -> None:
    """When model.stream=False, _complete calls complete() not stream()."""
    from agentforge.runtime.agent import AgentRuntime, RuntimeDeps
    from agentforge.sandbox.base import Sandbox
    from agentforge.sandbox.workspace import Workspace

    response = CompletionResponse(
        message=Message.assistant("non-streamed"),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=5, output_tokens=2),
        model="claude-opus-5",
    )
    provider = _FakeStreamProvider(["SHOULD", "NOT", "SEE"], response)

    events: list[RunEvent] = []

    class _Collector:
        async def on_event(self, event: RunEvent, run: Run) -> None:
            events.append(event)

    config = AgentConfig(
        name="test-no-stream",
        model=ModelConfig(provider="anthropic", stream=False),
        tools=[],
    )
    workspace = Workspace(root="/tmp/test-ws-no")
    executor = MagicMock()
    executor.specs = []
    deps = RuntimeDeps(
        provider=provider,
        executor=executor,
        workspace=workspace,
        sandbox=MagicMock(spec=Sandbox),
        observers=[_Collector()],
    )
    runtime = AgentRuntime(config, deps)
    run = Run(id="run_ns", agent_name="test", goal="test", config=config)
    step = Step(index=0, kind=StepKind.ACTION)
    request = _simple_request("claude-opus-5")

    result = await runtime._complete(run, step, request)

    delta_events = [e for e in events if e.type == "llm.delta"]
    assert len(delta_events) == 0  # no streaming
    assert result.message.text == "non-streamed"


# ===================================================================
#  ConsoleObserver streaming display
# ===================================================================


async def test_console_observer_streams_deltas() -> None:
    buf = io.StringIO()
    observer = ConsoleObserver(stream=buf)
    run = MagicMock(spec=Run)

    # First delta: prefix with ◇
    await observer.on_event(RunEvent(run_id="r", type="llm.delta", data={"text": "Hello"}), run)
    assert buf.getvalue() == "  ◇ Hello"

    # Second delta: appended inline
    await observer.on_event(RunEvent(run_id="r", type="llm.delta", data={"text": " world"}), run)
    assert buf.getvalue() == "  ◇ Hello world"

    # llm.finished ends the streaming line
    await observer.on_event(
        RunEvent(
            run_id="r",
            type="llm.finished",
            data={
                "step": 0,
                "attempts": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "stop_reason": "end_turn",
            },
        ),
        run,
    )
    assert buf.getvalue().endswith("\n")


async def test_console_observer_no_duplicate_thought_when_streaming() -> None:
    """step.finished should not print the thought summary if we were already streaming it."""
    buf = io.StringIO()
    observer = ConsoleObserver(stream=buf)
    run = MagicMock(spec=Run)
    step = MagicMock()
    step.thought = "Hello world"
    step.index = 0
    step.tool_calls = []
    run.steps = [step]

    # Stream the content
    await observer.on_event(RunEvent(run_id="r", type="llm.delta", data={"text": "Hello"}), run)
    await observer.on_event(RunEvent(run_id="r", type="llm.delta", data={"text": " world"}), run)

    # llm.finished ends streaming
    await observer.on_event(
        RunEvent(
            run_id="r",
            type="llm.finished",
            data={
                "step": 0,
                "attempts": 1,
                "input_tokens": 0,
                "output_tokens": 0,
                "stop_reason": "end_turn",
            },
        ),
        run,
    )

    # step.finished should not re-print the thought since _streaming was recently active
    buf_before = buf.getvalue()
    await observer.on_event(RunEvent(run_id="r", type="step.finished", data={"step": 0}), run)
    buf_after = buf.getvalue()
    # The thought line "[0] Hello world" should NOT appear since we streamed it
    added = buf_after[len(buf_before) :]
    assert "[0] Hello world" not in added


async def test_console_observer_retry_ends_streaming() -> None:
    buf = io.StringIO()
    observer = ConsoleObserver(stream=buf)
    run = MagicMock(spec=Run)

    await observer.on_event(RunEvent(run_id="r", type="llm.delta", data={"text": "partial"}), run)
    await observer.on_event(
        RunEvent(
            run_id="r",
            type="llm.retry",
            data={"step": 0, "attempt": 1, "error": "rate limit", "delay_seconds": 1.0},
        ),
        run,
    )
    output = buf.getvalue()
    assert "partial" in output
    assert "↻" in output
    assert output.count("\n") >= 1  # streaming line was terminated


# ===================================================================
#  Config
# ===================================================================


def test_model_config_stream_default_false() -> None:
    cfg = ModelConfig(provider="anthropic")
    assert cfg.stream is False


def test_model_config_stream_opt_in() -> None:
    cfg = ModelConfig(provider="anthropic", stream=True)
    assert cfg.stream is True
