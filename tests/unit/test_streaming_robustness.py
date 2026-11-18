"""Failure, cleanup and volume behaviour of streamed model output (T-003b).

``test_streaming.py`` covers the happy paths. These tests cover what a
streamed call must share with a plain one: provider errors arrive as
``LLMError`` (so the runtime's retry policy applies), connections are
released, token text never reaches the logs, and a provider that sends one
chunk per token does not turn into one event per token.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from agentforge.cli import ConsoleObserver
from agentforge.core.config import AgentConfig, ModelConfig, RetryPolicy
from agentforge.core.errors import LLMError, RunCancelledError
from agentforge.core.models import Run, Step, StepKind, TokenUsage
from agentforge.llm.anthropic import AnthropicProvider
from agentforge.llm.base import LLMProvider
from agentforge.llm.openai_compat import PRESETS, OpenAICompatibleProvider
from agentforge.llm.types import (
    CompletionRequest,
    CompletionResponse,
    CompletionStream,
    Message,
    StopReason,
    StreamDelta,
    ToolSpec,
)
from agentforge.runtime.agent import AgentRuntime, RuntimeDeps
from agentforge.runtime.events import LoggingObserver, RunEvent
from agentforge.sandbox.base import Sandbox
from agentforge.sandbox.workspace import Workspace


def _request(model: str = "m") -> CompletionRequest:
    return CompletionRequest(model=model, system="s", messages=[Message.user("hi")], max_tokens=64)


def _response(text: str = "Hello world") -> CompletionResponse:
    return CompletionResponse(
        message=Message.assistant(text),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=3, output_tokens=2),
        model="m",
    )


# --------------------------------------------------------------------- runtime


class _Stream(CompletionStream):
    """Yields ``chunks``; raises ``fail_after`` chunks in when ``error`` is set."""

    def __init__(
        self,
        chunks: list[str],
        response: CompletionResponse,
        *,
        error: Exception | None = None,
        fail_after: int = 0,
        on_chunk: Any = None,
    ) -> None:
        super().__init__()
        self._chunks = chunks
        self._final = response
        self._error = error
        self._fail_after = fail_after
        self._on_chunk = on_chunk
        self._index = 0
        self.closed = 0

    async def __anext__(self) -> StreamDelta:
        if self._error is not None and self._index >= self._fail_after:
            raise self._error
        if self._index >= len(self._chunks):
            self._response = self._final
            raise StopAsyncIteration
        text = self._chunks[self._index]
        self._index += 1
        if self._on_chunk is not None:
            self._on_chunk(self._index)
        return StreamDelta(text=text)

    async def aclose(self) -> None:
        self.closed += 1


class _Provider(LLMProvider):
    name = "third-party-plugin"

    def __init__(self, streams: list[_Stream]) -> None:
        self.streams = streams
        self.calls = 0

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        raise AssertionError("complete() must not be called when model.stream is set")

    async def stream(self, request: CompletionRequest) -> CompletionStream:
        self.calls += 1
        return self.streams[self.calls - 1]


def _runtime(
    provider: LLMProvider, tmp_path: Path, *, provider_name: str = "third-party-plugin"
) -> tuple[AgentRuntime, Run, Step, list[RunEvent]]:
    from unittest.mock import MagicMock

    events: list[RunEvent] = []

    class _Collector:
        async def on_event(self, event: RunEvent, run: Run) -> None:
            events.append(event)

    config = AgentConfig(
        name="streamer",
        model=ModelConfig(provider=provider_name, model="m", stream=True),
        tools=[],
        retry=RetryPolicy(llm_max_attempts=2, backoff_initial_seconds=0.0),
    )
    executor = MagicMock()
    executor.specs = []
    deps = RuntimeDeps(
        provider=provider,
        executor=executor,
        workspace=Workspace(root=tmp_path),
        sandbox=MagicMock(spec=Sandbox),
        observers=[_Collector()],
    )
    run = Run(id="run_s", agent_name="streamer", goal="g", config=config)
    return AgentRuntime(config, deps), run, Step(index=0, kind=StepKind.ACTION), events


def _delta_texts(events: list[RunEvent]) -> list[str]:
    return [e.data["text"] for e in events if e.type == "llm.delta"]


async def test_streaming_is_not_limited_to_built_in_provider_names(tmp_path: Path) -> None:
    """A plugin provider that implements stream() is streamed like a built-in one."""
    stream = _Stream(["Hel", "lo"], _response("Hello"))
    runtime, run, step, events = _runtime(_Provider([stream]), tmp_path)

    result = await runtime._complete(run, step, _request())

    assert result.message.text == "Hello"
    assert "".join(_delta_texts(events)) == "Hello"
    assert stream.closed == 1


async def test_deltas_are_coalesced_between_flushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One chunk per token must not become one event per token."""
    monkeypatch.setattr("agentforge.runtime.agent.STREAM_FLUSH_SECONDS", 3600.0)
    chunks = [f"t{i} " for i in range(200)]
    stream = _Stream(chunks, _response("".join(chunks)))
    runtime, run, step, events = _runtime(_Provider([stream]), tmp_path)

    await runtime._complete(run, step, _request())

    texts = _delta_texts(events)
    assert texts[0] == "t0 "  # the first chunk is shown at once
    assert len(texts) == 2  # ...and the rest arrives with the final flush
    assert "".join(texts) == "".join(chunks)  # nothing lost, order kept
    # The deltas precede the call's llm.finished event.
    types = [e.type for e in events]
    assert types.index("llm.finished") > max(i for i, t in enumerate(types) if t == "llm.delta")


async def test_stream_failing_midway_is_retried_and_closed(tmp_path: Path) -> None:
    broken = _Stream(
        ["par", "tial"],
        _response(),
        error=LLMError("connection dropped", retryable=True, code="connection"),
        fail_after=1,
    )
    good = _Stream(["Hello world"], _response())
    provider = _Provider([broken, good])
    runtime, run, step, events = _runtime(provider, tmp_path)

    result = await runtime._complete(run, step, _request())

    assert provider.calls == 2
    assert broken.closed == 1 and good.closed == 1
    assert result.message.text == "Hello world"
    assert step.llm_call is not None and step.llm_call.attempts == 2
    # Consumers are told to drop the partial text before the second attempt's.
    types = [e.type for e in events]
    assert types == ["llm.delta", "llm.retry", "llm.delta", "llm.finished"]
    # Usage is counted once, from the attempt that completed.
    assert run.usage.input_tokens == 3 and run.usage.output_tokens == 2


async def test_non_retryable_stream_error_is_recorded_and_closed(tmp_path: Path) -> None:
    broken = _Stream(
        [], _response(), error=LLMError("bad key", retryable=False, code="authentication")
    )
    runtime, run, step, _events = _runtime(_Provider([broken]), tmp_path)

    with pytest.raises(LLMError):
        await runtime._complete(run, step, _request())

    assert broken.closed == 1
    assert step.llm_call is not None and step.llm_call.error is not None
    assert step.llm_call.error.type == "llm.authentication"


async def test_cancel_during_stream_stops_reading_and_closes(tmp_path: Path) -> None:
    runtime: AgentRuntime

    def cancel_on_second(index: int) -> None:
        if index == 2:
            runtime.cancel()

    stream = _Stream(["a", "b", "c", "d"], _response("abcd"), on_chunk=cancel_on_second)
    runtime, run, step, events = _runtime(_Provider([stream]), tmp_path)

    with pytest.raises(RunCancelledError):
        await runtime._stream_completion(run, step, _request())

    assert stream.closed == 1
    assert "".join(_delta_texts(events)) == "a"  # nothing after the cancel


async def test_provider_without_native_streaming_still_answers(tmp_path: Path) -> None:
    """model.stream on a provider that only implements complete(): same answer, no deltas."""

    class _Plain(LLMProvider):
        name = "plain"

        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            return _response("plain answer")

    runtime, run, step, events = _runtime(_Plain(), tmp_path, provider_name="plain")

    result = await runtime._complete(run, step, _request())

    assert result.message.text == "plain answer"
    assert _delta_texts(events) == []


# --------------------------------------------------------------------- logging


async def test_token_text_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Deltas carry model output (which may quote file contents): keep them out of logs."""
    run = Run(
        id="run_l",
        agent_name="a",
        goal="g",
        config=AgentConfig(name="a", model=ModelConfig(provider="scripted")),
    )
    observer = LoggingObserver()
    with caplog.at_level(logging.INFO, logger="agentforge.runtime"):
        await observer.on_event(
            RunEvent(run_id=run.id, type="llm.delta", data={"step": 0, "text": "TOP-SECRET"}), run
        )
        await observer.on_event(RunEvent(run_id=run.id, type="llm.finished", data={"step": 0}), run)
    assert [r.getMessage() for r in caplog.records] == ["llm.finished"]
    assert all("TOP-SECRET" not in str(r.__dict__) for r in caplog.records)


def test_persistence_ignores_deltas() -> None:
    """A streamed run must not write the run record once per flush."""
    from agentforge.storage import _PERSIST_ON

    assert "llm.delta" not in _PERSIST_ON


# ------------------------------------------------------------------- Anthropic


def _anthropic_sse(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


_ANTHROPIC_EVENTS: list[tuple[str, dict[str, Any]]] = [
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 1},
            },
        },
    ),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Reading "},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "the file."},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_file",
                "input": {},
            },
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"path": '},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '"a.txt"}'},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 17},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
]


def _anthropic_client(handler: Any) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key="test-key",
        base_url="http://anthropic.test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


async def test_anthropic_stream_through_the_real_sdk() -> None:
    """The adapter against the SDK's own SSE parsing: text deltas, tool call, usage."""
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return httpx2.Response(
            200,
            content=_anthropic_sse(_ANTHROPIC_EVENTS),
            headers={"content-type": "text/event-stream"},
        )

    provider = AnthropicProvider(client=_anthropic_client(handler))
    stream = await provider.stream(_request("claude-test"))
    deltas = [d.text async for d in stream]
    await stream.aclose()

    assert seen["stream"] is True
    assert deltas == ["Reading ", "the file."]
    response = stream.response
    assert response.message.text == "Reading the file."
    assert [(t.id, t.name, t.arguments) for t in response.message.tool_uses] == [
        ("toolu_1", "read_file", {"path": "a.txt"})
    ]
    assert response.stop_reason == StopReason.TOOL_USE
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 17
    assert response.model == "claude-test"
    assert response.response_id == "msg_1"


async def test_anthropic_stream_http_error_is_a_retryable_llm_error() -> None:
    """The request is sent on first iteration; its failure must be an LLMError."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
        )

    provider = AnthropicProvider(client=_anthropic_client(handler))
    stream = await provider.stream(_request("claude-test"))
    with pytest.raises(LLMError) as excinfo:
        async for _ in stream:
            pass
    assert excinfo.value.retryable is True
    assert excinfo.value.status_code == 529
    await stream.aclose()  # idempotent after a failure


async def test_anthropic_stream_auth_error_is_not_retryable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "no"}},
        )

    provider = AnthropicProvider(client=_anthropic_client(handler))
    stream = await provider.stream(_request("claude-test"))
    with pytest.raises(LLMError) as excinfo:
        async for _ in stream:
            pass
    assert excinfo.value.retryable is False
    assert excinfo.value.code == "authentication"


class _Manager:
    """Stands in for the SDK's stream manager to observe enter/exit."""

    def __init__(self, texts: list[str], error: Exception | None = None) -> None:
        self.exits = 0
        self._texts = texts
        self._error = error

    async def __aenter__(self) -> _Manager:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.exits += 1

    @property
    def text_stream(self) -> Any:
        async def gen() -> Any:
            for text in self._texts:
                yield text
            if self._error is not None:
                raise self._error

        return gen()

    async def get_final_message(self) -> Any:
        raise AssertionError("not reached in these tests")


async def test_anthropic_stream_error_midway_is_translated_and_released() -> None:
    from agentforge.llm.anthropic import _AnthropicStream

    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "http://anthropic.test"))
    manager = _Manager(["partial"], error)
    stream = _AnthropicStream(manager, "claude-test")

    assert (await stream.__anext__()).text == "partial"
    with pytest.raises(LLMError) as excinfo:
        await stream.__anext__()
    assert excinfo.value.retryable is True
    assert excinfo.value.code == "connection"
    assert manager.exits == 1


async def test_anthropic_stream_abandoned_early_is_released_once() -> None:
    from agentforge.llm.anthropic import _AnthropicStream

    manager = _Manager(["a", "b", "c"])
    stream = _AnthropicStream(manager, "claude-test")
    assert (await stream.__anext__()).text == "a"

    await stream.aclose()
    await stream.aclose()

    assert manager.exits == 1
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    with pytest.raises(RuntimeError):
        _ = stream.response  # no complete response exists


# ----------------------------------------------------------- OpenAI-compatible


def _openai_client(handler: Any) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        api_key="test-key",
        base_url="http://openai.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


def _sse(chunks: list[dict[str, Any]]) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})


def _chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-test",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


async def test_openai_stream_sends_the_same_request_as_complete() -> None:
    """Streaming differs from a plain call only by the two streaming fields."""
    bodies: list[dict[str, Any]] = []
    headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        headers.append(request.headers)
        if body.get("stream"):
            return _sse([_chunk({"content": "ok"}), _chunk({}, "stop")])
        return httpx2.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    provider = OpenAICompatibleProvider(
        PRESETS["opencode-go"], client=_openai_client(handler), extra_params={"top_p": 0.5}
    )
    request = CompletionRequest(
        model="some-model",
        system="s",
        messages=[Message.user("hi")],
        max_tokens=64,
        temperature=0.2,
        session_id="run_42",
        tools=[
            ToolSpec(name="read_file", description="d", input_schema={"type": "object"}),
        ],
    )
    await provider.complete(request)
    stream = await provider.stream(request)
    async for _ in stream:
        pass

    plain, streamed = bodies
    assert streamed.pop("stream") is True
    assert streamed.pop("stream_options") == {"include_usage": True}
    assert streamed == plain
    assert plain["tools"][0]["function"]["name"] == "read_file"
    assert plain["top_p"] == 0.5
    session_header = PRESETS["opencode-go"].session_header
    assert session_header is not None
    assert headers[0][session_header] == headers[1][session_header] == "run_42"


async def test_openai_stream_without_any_choice_is_a_retryable_error() -> None:
    """An empty stream is the streamed form of "response contained no choices"."""
    provider = OpenAICompatibleProvider(
        PRESETS["openai"], client=_openai_client(lambda request: _sse([]))
    )
    stream = await provider.stream(_request("gpt-test"))
    with pytest.raises(LLMError) as excinfo:
        async for _ in stream:
            pass
    assert excinfo.value.retryable is True
    assert "no choices" in excinfo.value.message


async def test_openai_stream_http_error_is_translated() -> None:
    provider = OpenAICompatibleProvider(
        PRESETS["openai"],
        client=_openai_client(
            lambda request: httpx2.Response(429, json={"error": {"message": "slow down"}})
        ),
    )
    with pytest.raises(LLMError) as excinfo:
        await provider.stream(_request("gpt-test"))
    assert excinfo.value.retryable is True
    assert excinfo.value.status_code == 429


async def test_openai_stream_abandoned_early_closes_the_sdk_stream() -> None:
    from agentforge.llm.openai_compat import _OpenAIStream

    class _Sdk:
        closed = 0

        def __aiter__(self) -> Any:
            async def gen() -> Any:
                from types import SimpleNamespace

                for text in ("a", "b"):
                    yield SimpleNamespace(
                        choices=[
                            SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)
                        ]
                    )

            return gen()

        async def close(self) -> None:
            _Sdk.closed += 1

    stream = _OpenAIStream(_Sdk(), "openai", "gpt-test")
    assert (await stream.__anext__()).text == "a"
    await stream.aclose()
    await stream.aclose()
    assert _Sdk.closed == 1
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


# --------------------------------------------------------------------- console


async def test_console_ends_the_token_line_when_a_streamed_call_fails() -> None:
    """A failed call emits no llm.finished: the next line must still start fresh."""
    import io

    out = io.StringIO()
    observer = ConsoleObserver(stream=out)
    config = AgentConfig(name="a", model=ModelConfig(provider="scripted"))
    run = Run(id="run_c", agent_name="a", goal="g", config=config)
    run.steps.append(Step(index=0, kind=StepKind.ACTION))

    await observer.on_event(RunEvent(run_id=run.id, type="llm.delta", data={"text": "par"}), run)
    await observer.on_event(
        RunEvent(run_id=run.id, type="step.finished", data={"step": 0, "error": "boom"}), run
    )
    await observer.on_event(RunEvent(run_id=run.id, type="run.finished", data={}), run)

    lines = out.getvalue().splitlines()
    assert lines[0] == "  ◇ par"
    assert lines[-1].startswith("■ ")
