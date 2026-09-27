"""Provider adapters are tested against the real SDKs with a mocked HTTP transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from agentforge.core.config import ModelConfig
from agentforge.core.errors import ConfigurationError, LLMError
from agentforge.core.models import TokenUsage
from agentforge.llm.anthropic import AnthropicProvider, to_anthropic_messages
from agentforge.llm.openai_compat import PRESETS, OpenAICompatibleProvider, to_openai_messages
from agentforge.llm.pricing import ModelPrice, PriceTable
from agentforge.llm.registry import available_providers, create_provider
from agentforge.llm.scripted import ScriptedProvider
from agentforge.llm.types import (
    CompletionRequest,
    Message,
    ProviderPart,
    Role,
    StopReason,
    TextPart,
    ToolResultPart,
    ToolSpec,
    ToolUsePart,
)

Handler = Callable[[httpx2.Request], httpx2.Response]

CONVERSATION = [
    Message.user("Read a.txt"),
    Message(
        role=Role.ASSISTANT,
        content=[
            ProviderPart(
                provider="anthropic", data={"type": "thinking", "thinking": "", "signature": "s"}
            ),
            TextPart(text="Reading."),
            ToolUsePart(id="tu_1", name="read_file", arguments={"path": "a.txt"}),
        ],
    ),
    Message(role=Role.USER, content=[ToolResultPart(tool_use_id="tu_1", content="hello")]),
]
TOOLS = [ToolSpec(name="read_file", description="Read", input_schema={"type": "object"})]


def anthropic_client(handler: Handler) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key="test-key",
        base_url="http://anthropic.test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


def openai_client(handler: Handler) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        api_key="test-key",
        base_url="http://openai.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


# --------------------------------------------------------------------- anthropic
def test_to_anthropic_messages_translates_all_parts() -> None:
    out = to_anthropic_messages(CONVERSATION)
    assert out[0] == {"role": "user", "content": [{"type": "text", "text": "Read a.txt"}]}
    assistant = out[1]["content"]
    assert assistant[0]["type"] == "thinking"  # opaque block echoed back unchanged
    assert assistant[2] == {
        "type": "tool_use",
        "id": "tu_1",
        "name": "read_file",
        "input": {"path": "a.txt"},
    }
    assert out[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": "hello",
        "is_error": False,
    }


def test_foreign_provider_parts_are_dropped() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=[ProviderPart(provider="other", data={"x": 1}), TextPart(text="hi")],
    )
    assert to_anthropic_messages([msg])[0]["content"] == [{"type": "text", "text": "hi"}]


async def test_anthropic_complete_parses_tool_use_and_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers.get("x-api-key")
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "tu_2", "name": "read_file", "input": {"path": "b"}},
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 7,
                    "cache_creation_input_tokens": 3,
                },
            },
        )

    provider = AnthropicProvider(client=anthropic_client(handler))
    response = await provider.complete(
        CompletionRequest(model="claude-opus-5", system="sys", messages=CONVERSATION, tools=TOOLS)
    )
    assert seen["key"] == "test-key"
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["tools"][0]["input_schema"] == {"type": "object"}
    assert response.stop_reason == StopReason.TOOL_USE
    assert response.message.tool_uses[0].arguments == {"path": "b"}
    assert response.usage == TokenUsage(
        input_tokens=100, output_tokens=20, cache_read_tokens=7, cache_write_tokens=3
    )
    assert response.response_id == "msg_1"


@pytest.mark.parametrize(
    ("status", "retryable", "code"),
    [
        (429, True, "rate_limit"),
        (500, True, "api_status"),
        (529, True, "api_status"),
        (400, False, "api_status"),
        (401, False, "authentication"),
    ],
)
async def test_anthropic_errors_are_classified(status: int, retryable: bool, code: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "boom"}}
        )

    provider = AnthropicProvider(client=anthropic_client(handler))
    with pytest.raises(LLMError) as info:
        await provider.complete(CompletionRequest(model="m", messages=[Message.user("hi")]))
    assert info.value.retryable is retryable
    assert info.value.code == code
    assert "test-key" not in info.value.message


async def test_anthropic_connection_error_is_retryable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    provider = AnthropicProvider(client=anthropic_client(handler))
    with pytest.raises(LLMError) as info:
        await provider.complete(CompletionRequest(model="m", messages=[Message.user("hi")]))
    assert info.value.retryable


def test_anthropic_requires_key() -> None:
    with pytest.raises(ConfigurationError):
        AnthropicProvider(api_key=None)


# ------------------------------------------------------------------------ openai
def test_to_openai_messages_splits_tool_results() -> None:
    out = to_openai_messages("sys", CONVERSATION)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {
        "name": "read_file",
        "arguments": json.dumps({"path": "a.txt"}),
    }
    assert out[3] == {"role": "tool", "tool_call_id": "tu_1", "content": "hello"}


async def test_openai_complete_parses_tool_calls() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path": "x"}'},
                                },
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": "{not json"},
                                },
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
            },
        )

    provider = OpenAICompatibleProvider(PRESETS["openai"], client=openai_client(handler))
    response = await provider.complete(
        CompletionRequest(
            model="gpt-test", messages=[Message.user("hi")], tools=TOOLS, max_tokens=50
        )
    )
    assert seen["body"]["max_completion_tokens"] == 50
    assert seen["body"]["tools"][0]["function"]["name"] == "read_file"
    assert response.stop_reason == StopReason.TOOL_USE
    calls = response.message.tool_uses
    assert calls[0].arguments == {"path": "x"}
    assert "__invalid_json__" in calls[1].arguments
    assert response.usage.input_tokens == 11


async def test_openai_compat_presets_use_max_tokens_param() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "done"},
                    }
                ],
            },
        )

    provider = OpenAICompatibleProvider(PRESETS["local"], client=openai_client(handler))
    response = await provider.complete(
        CompletionRequest(model="llama", messages=[Message.user("hi")], max_tokens=10)
    )
    assert seen["body"]["max_tokens"] == 10
    assert response.message.text == "done"
    assert response.stop_reason == StopReason.END_TURN


async def test_openai_requires_model() -> None:
    provider = OpenAICompatibleProvider(PRESETS["local"], client=object())
    with pytest.raises(ConfigurationError):
        await provider.complete(CompletionRequest(model="", messages=[Message.user("hi")]))


async def test_openai_rate_limit_is_retryable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, json={"error": {"message": "slow down"}})

    provider = OpenAICompatibleProvider(PRESETS["openrouter"], client=openai_client(handler))
    with pytest.raises(LLMError) as info:
        await provider.complete(CompletionRequest(model="m", messages=[Message.user("hi")]))
    assert info.value.retryable
    assert info.value.code == "rate_limit"


# ---------------------------------------------------------------------- registry
def test_registry_lists_required_providers() -> None:
    names = {p.name for p in available_providers()}
    assert {"anthropic", "openai", "gemini", "openrouter", "local", "scripted"} <= names


def test_create_provider_unknown() -> None:
    with pytest.raises(ConfigurationError):
        create_provider(ModelConfig(provider="nope"), {})


def test_create_provider_reads_key_from_configured_env() -> None:
    provider = create_provider(
        ModelConfig(provider="anthropic", api_key_env="MY_KEY"), {"MY_KEY": "k-123456789"}
    )
    assert isinstance(provider, AnthropicProvider)
    with pytest.raises(ConfigurationError):
        create_provider(ModelConfig(provider="openai", model="m"), {})


def test_local_provider_needs_no_key() -> None:
    provider = create_provider(ModelConfig(provider="local", model="llama"), {})
    assert provider.name == "local"


# ----------------------------------------------------------------------- scripted
async def test_scripted_provider_replays_turns() -> None:
    provider = ScriptedProvider.from_options(
        {
            "turns": [
                {"text": "a", "tool_calls": [{"name": "t", "arguments": {"x": 1}}]},
                {"text": "b"},
            ]
        }
    )
    history = [Message.user("goal")]
    first = await provider.complete(CompletionRequest(model="", messages=history))
    assert first.stop_reason == StopReason.TOOL_USE
    history.append(first.message)
    second = await provider.complete(CompletionRequest(model="", messages=history))
    assert second.message.text == "b"
    assert second.usage.total_tokens == 0


async def test_scripted_rules_select_by_goal() -> None:
    provider = ScriptedProvider.from_options(
        {
            "turns": [{"text": "default"}],
            "rules": [{"when": "special", "turns": [{"text": "rule"}]}],
        }
    )
    special = await provider.complete(
        CompletionRequest(model="", messages=[Message.user("a special goal")])
    )
    other = await provider.complete(CompletionRequest(model="", messages=[Message.user("other")]))
    assert (special.message.text, other.message.text) == ("rule", "default")


async def test_scripted_error_turn_then_recovers() -> None:
    provider = ScriptedProvider.from_options(
        {"turns": [{"error": {"message": "flaky", "retryable": True}}, {"text": "ok"}]}
    )
    request = CompletionRequest(model="", messages=[Message.user("g")])
    with pytest.raises(LLMError):
        await provider.complete(request)
    assert (await provider.complete(request)).message.text == "ok"


async def test_scripted_exhausted_modes() -> None:
    finish = ScriptedProvider.from_options({"turns": []})
    assert (
        await finish.complete(CompletionRequest(model="", messages=[Message.user("g")]))
    ).message.text
    error = ScriptedProvider.from_options({"turns": [], "on_exhausted": "error"})
    with pytest.raises(LLMError):
        await error.complete(CompletionRequest(model="", messages=[Message.user("g")]))


# ------------------------------------------------------------------------ pricing
def test_price_table_known_and_unknown() -> None:
    table = PriceTable()
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert table.estimate("anthropic", "claude-opus-5", usage) == pytest.approx(30.0)
    assert table.estimate("openai", "some-model", usage) is None
    assert table.estimate("scripted", "anything", usage) == 0.0


def test_price_without_cache_rate_returns_none() -> None:
    price = ModelPrice(input=1.0, output=1.0)
    assert price.cost(TokenUsage(input_tokens=10, cache_read_tokens=5)) is None


def test_price_table_from_file(tmp_path: Any) -> None:
    path = tmp_path / "prices.yaml"
    path.write_text("openai:\n  my-model: {input: 2.0, output: 8.0}\n")
    table = PriceTable.from_file(path)
    usage = TokenUsage(input_tokens=500_000, output_tokens=250_000)
    assert table.estimate("openai", "my-model", usage) == pytest.approx(3.0)


# -------------------------------------------------------------------- opencode-go
def test_opencode_go_requires_explicit_endpoint() -> None:
    # Without a base_url the key must never go to the OpenAI SDK's default host.
    with pytest.raises(ConfigurationError, match=r"requires model\.base_url"):
        create_provider(
            ModelConfig(provider="opencode-go", model="m"), {"OPENCODE_API_KEY": "k-123456789"}
        )
    with pytest.raises(ConfigurationError, match="no API key"):
        create_provider(
            ModelConfig(provider="opencode-go", model="m", base_url="https://go.test/v1"), {}
        )
    provider = create_provider(
        ModelConfig(provider="opencode-go", model="m", base_url="https://go.test/v1"),
        {"OPENCODE_API_KEY": "k-123456789"},
    )
    assert provider.name == "opencode-go"
    info = {p.name: p for p in available_providers()}["opencode-go"]
    assert info.api_key_env == "OPENCODE_API_KEY" and info.requires_model


async def test_opencode_go_speaks_chat_completions() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "model": "glm-5.3-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path": "a"}'},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatibleProvider(PRESETS["opencode-go"], client=openai_client(handler))
    response = await provider.complete(
        CompletionRequest(model="glm-5.3-flash", messages=[Message.user("hi")], max_tokens=64)
    )
    assert seen["max_tokens"] == 64 and "max_completion_tokens" not in seen
    assert response.stop_reason == StopReason.TOOL_USE
    assert response.message.tool_uses[0].arguments == {"path": "a"}
    assert (response.usage.input_tokens, response.usage.output_tokens) == (12, 3)


# ---------------------------------------------- opencode-go: session, auth modes
OC_KEY = "oc-unit-key-7d1e0c2b9a584f36"


def _chat_ok(model: str = "deepseek-v4.1-flash") -> dict[str, Any]:
    return {
        "id": "x",
        "model": model,
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    }


def opencode_handler(seen: list[httpx2.Request]) -> Handler:
    """Rejects requests without x-opencode-session, exactly like OpenCode Go (HTTP 400)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if not request.headers.get("x-opencode-session"):
            return httpx2.Response(
                400, json={"error": {"type": "MissingSessionID", "message": "missing session"}}
            )
        return httpx2.Response(200, json=_chat_ok())

    return handler


def _request(session_id: str | None) -> CompletionRequest:
    return CompletionRequest(
        model="deepseek-v4.1-flash",
        messages=[Message.user("hi")],
        max_tokens=16,
        session_id=session_id,
    )


async def test_missing_session_header_is_what_opencode_rejects() -> None:
    # The original bug: a plain OpenAI-compatible request has no session header.
    seen: list[httpx2.Request] = []
    provider = OpenAICompatibleProvider(
        PRESETS["openai"], client=openai_client(opencode_handler(seen))
    )
    with pytest.raises(LLMError, match="400"):
        await provider.complete(_request("run_a"))
    assert "x-opencode-session" not in seen[0].headers  # other presets never send it


async def test_opencode_go_sends_stable_session_per_run() -> None:
    seen: list[httpx2.Request] = []
    provider = OpenAICompatibleProvider(
        PRESETS["opencode-go"], client=openai_client(opencode_handler(seen))
    )
    for _ in range(2):  # two model calls of one run (or a retry of the same request)
        response = await provider.complete(_request("run_a"))
        assert response.message.text == "ok"
    await provider.complete(_request("run_b"))
    sessions = [r.headers["x-opencode-session"] for r in seen]
    assert sessions == ["run_a", "run_a", "run_b"]
    assert all(r.url.path.endswith("/chat/completions") for r in seen)
    assert all(r.headers["user-agent"].startswith("agentforge/") for r in seen)


async def test_opencode_go_session_fallback_is_per_provider_not_per_request() -> None:
    seen: list[httpx2.Request] = []
    first = OpenAICompatibleProvider(
        PRESETS["opencode-go"], client=openai_client(opencode_handler(seen))
    )
    second = OpenAICompatibleProvider(
        PRESETS["opencode-go"], client=openai_client(opencode_handler(seen))
    )
    await first.complete(_request(None))
    await first.complete(_request(None))
    await second.complete(_request(None))
    a1, a2, b = (r.headers["x-opencode-session"] for r in seen)
    assert a1 == a2 != b
    assert len(a1) == 32 and int(a1, 16) >= 0  # a uuid4 hex: nothing derived from a credential


async def test_session_header_never_carries_the_key() -> None:
    seen: list[httpx2.Request] = []
    client = openai.AsyncOpenAI(
        api_key=OC_KEY,
        base_url="http://go.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(opencode_handler(seen))
        ),
    )
    provider = OpenAICompatibleProvider(PRESETS["opencode-go"], client=client)
    await provider.complete(_request("run_a"))
    headers = seen[0].headers
    assert headers["authorization"] == f"Bearer {OC_KEY}"  # api_key mode: bearer auth
    assert OC_KEY not in headers["x-opencode-session"] and OC_KEY not in headers["user-agent"]


async def test_proxy_auth_sends_no_authorization_header() -> None:
    seen: list[httpx2.Request] = []
    # Even a client that holds a key sends none in proxy mode: the proxy injects it.
    provider = OpenAICompatibleProvider(
        PRESETS["opencode-go"], client=openai_client(opencode_handler(seen)), auth="proxy"
    )
    await provider.complete(_request("run_a"))
    assert "authorization" not in seen[0].headers
    assert seen[0].headers["x-opencode-session"] == "run_a"


async def test_proxy_auth_via_registry_reads_no_key_and_sends_none() -> None:
    config = ModelConfig(
        provider="opencode-go",
        model="deepseek-v4.1-flash",
        base_url="http://go.test/v1",
        options={"auth": "proxy"},
    )
    # No key in the environment: proxy mode must not require one...
    provider = create_provider(config, {})
    assert isinstance(provider, OpenAICompatibleProvider)
    # ...and a key that is present is not read either.
    provider = create_provider(config, {"OPENCODE_API_KEY": OC_KEY})
    assert isinstance(provider, OpenAICompatibleProvider)
    seen: list[httpx2.Request] = []
    provider._client = provider._client.with_options(
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(opencode_handler(seen))
        )
    )
    await provider.complete(_request("run_a"))
    assert "authorization" not in seen[0].headers
    assert all(OC_KEY not in value for value in seen[0].headers.values())
    assert provider._client.max_retries == 0  # retry policy stays with the runtime


def test_unknown_auth_mode_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="unknown auth mode"):
        create_provider(
            ModelConfig(
                provider="opencode-go",
                model="m",
                base_url="http://go.test/v1",
                options={"auth": "cookie"},
            ),
            {"OPENCODE_API_KEY": OC_KEY},
        )


async def test_opencode_go_routes_responses_models_to_responses_api() -> None:
    seen: list[httpx2.Request] = []
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        body = json.loads(request.content)
        bodies.append(body)
        assert request.url.path.endswith("/responses")
        if not request.headers.get("x-opencode-session"):
            return httpx2.Response(400, json={"error": {"type": "MissingSessionID"}})
        return httpx2.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 0,
                "model": body["model"],
                "status": "completed",
                "output": [
                    {"type": "reasoning", "id": "rs_1", "summary": []},
                    {
                        "type": "message",
                        "id": "m1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Reading.", "annotations": []}],
                    },
                    {
                        "type": "function_call",
                        "id": "fc1",
                        "call_id": "call_9",
                        "name": "read_file",
                        "arguments": '{"path": "b.txt"}',
                        "status": "completed",
                    },
                ],
                "usage": {
                    "input_tokens": 30,
                    "output_tokens": 7,
                    "total_tokens": 37,
                    "input_tokens_details": {"cached_tokens": 4},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    provider = OpenAICompatibleProvider(PRESETS["opencode-go"], client=openai_client(handler))
    response = await provider.complete(
        CompletionRequest(
            model="muse-spark-1.3-contributor",
            system="Be brief.",
            messages=CONVERSATION,
            tools=TOOLS,
            max_tokens=64,
            session_id="run_m",
        )
    )
    body = bodies[0]
    assert seen[0].headers["x-opencode-session"] == "run_m"
    assert body["instructions"] == "Be brief." and body["max_output_tokens"] == 64
    assert body["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read",
            "parameters": {"type": "object"},
        }
    ]
    assert body["input"] == [
        {"role": "user", "content": "Read a.txt"},
        {"role": "assistant", "content": "Reading."},
        {
            "type": "function_call",
            "call_id": "tu_1",
            "name": "read_file",
            "arguments": '{"path": "a.txt"}',
        },
        {"type": "function_call_output", "call_id": "tu_1", "output": "hello"},
    ]
    assert response.stop_reason == StopReason.TOOL_USE
    assert response.message.text == "Reading."
    assert response.message.tool_uses[0].id == "call_9"
    assert response.message.tool_uses[0].arguments == {"path": "b.txt"}
    usage = response.usage
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (30, 7, 4)


async def test_opencode_go_refuses_messages_api_models_without_a_request() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request may be sent")

    provider = OpenAICompatibleProvider(PRESETS["opencode-go"], client=openai_client(handler))
    with pytest.raises(LLMError, match="'messages' endpoint") as info:
        await provider.complete(
            CompletionRequest(model="qwen3.8-max", messages=[Message.user("x")], session_id="r")
        )
    assert info.value.code == "unsupported_api" and not info.value.retryable
