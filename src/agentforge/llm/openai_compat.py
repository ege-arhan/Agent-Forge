"""OpenAI Chat Completions / Responses adapter (official ``openai`` SDK).

The Chat Completions wire format is the de-facto standard for many endpoints,
so this one adapter serves several provider presets:

* ``openai``      - api.openai.com
* ``openrouter``  - openrouter.ai (hundreds of hosted models)
* ``gemini``      - Google's OpenAI-compatible Gemini endpoint
* ``local``       - any local OpenAI-compatible server (Ollama, vLLM, LM Studio,
  llama.cpp server); defaults to Ollama's address.
* ``opencode-go`` - OpenCode Go (endpoint set via ``model.base_url``). Every
  request carries ``x-opencode-session`` (a stable id per conversation: the
  AgentForge run id) and an ``agentforge/<version>`` user agent, as OpenCode Go
  requires; models that OpenCode serves on ``/responses`` use the Responses API.

Authentication modes (``model.options.auth``):

* ``api_key`` (default) - the key is read from ``model.api_key_env`` (or the
  preset's variable) and sent as ``Authorization: Bearer``.
* ``proxy`` - an egress proxy injects the credential into outbound requests
  (e.g. a Claude Cloud environment's API Credentials). No key is read from the
  environment and the request carries no ``Authorization`` header, so the
  secret never enters this process.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agentforge import __version__
from agentforge.core.errors import ConfigurationError, LLMError
from agentforge.core.models import TokenUsage
from agentforge.llm.base import LLMProvider
from agentforge.llm.types import (
    CompletionRequest,
    CompletionResponse,
    ContentPart,
    Message,
    Role,
    StopReason,
    TextPart,
    ToolResultPart,
    ToolUsePart,
)


@dataclass(frozen=True)
class OpenAICompatPreset:
    name: str
    base_url: str | None
    api_key_env: str | None
    requires_key: bool = True
    token_param: str = "max_tokens"  # noqa: S105 - request field name, not a secret
    # Presets without a fixed endpoint must never fall back to the OpenAI SDK's
    # default host (that would send their key to api.openai.com).
    requires_base_url: bool = False
    # Header carrying a stable per-conversation id (OpenCode Go: routing and caching).
    session_header: str | None = None
    # Send an ``agentforge/<version>`` user agent instead of the SDK's generic one.
    identify_client: bool = False
    # Models served on another wire API than Chat Completions: "responses" is
    # spoken here, "messages" (Anthropic format) is refused before any request.
    model_apis: Mapping[str, str] = field(default_factory=dict)


# OpenCode Go endpoint table (https://opencode.ai/docs/go/, "Endpoints"; checked
# 2026-09-27). Its /models listing carries no endpoint metadata, so this is the
# source; every model not listed here uses /chat/completions.
OPENCODE_GO_MODEL_APIS: dict[str, str] = {
    **dict.fromkeys(
        [
            "grok-4.7",
            "grok-4.6",
            "gpt-6-luna",
            "gpt-5.6-luna",
            "muse-spark-1.3-contributor",
            "muse-spark-1.2-contributor",
        ],
        "responses",
    ),
    **dict.fromkeys(
        [
            "minimax-m3",
            "minimax-m2.7",
            "minimax-m2.5",
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.6-plus",
        ],
        "messages",
    ),
}
OPENCODE_SESSION_HEADER = "x-opencode-session"


PRESETS: dict[str, OpenAICompatPreset] = {
    "openai": OpenAICompatPreset(
        name="openai",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        token_param="max_completion_tokens",  # noqa: S106
    ),
    "openrouter": OpenAICompatPreset(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    ),
    "gemini": OpenAICompatPreset(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
    ),
    "opencode-go": OpenAICompatPreset(
        name="opencode-go",
        base_url=None,
        api_key_env="OPENCODE_API_KEY",
        requires_base_url=True,
        session_header=OPENCODE_SESSION_HEADER,
        identify_client=True,
        model_apis=OPENCODE_GO_MODEL_APIS,
    ),
    "local": OpenAICompatPreset(
        name="local",
        base_url="http://localhost:11434/v1",
        api_key_env=None,
        requires_key=False,
    ),
}

AUTH_MODES = ("api_key", "proxy")

_FINISH_REASONS = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
}


def to_openai_messages(system: str | None, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for message in messages:
        texts = [p.text for p in message.content if isinstance(p, TextPart) and p.text]
        if message.role == Role.ASSISTANT:
            entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            tool_calls = [
                {
                    "id": p.id,
                    "type": "function",
                    "function": {"name": p.name, "arguments": json.dumps(p.arguments)},
                }
                for p in message.content
                if isinstance(p, ToolUsePart)
            ]
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
            continue
        # User turn: tool results become individual ``tool`` messages first.
        for part in message.content:
            if isinstance(part, ToolResultPart):
                content = f"ERROR: {part.content}" if part.is_error else part.content
                out.append({"role": "tool", "tool_call_id": part.tool_use_id, "content": content})
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})
    return out


def to_responses_input(messages: list[Message]) -> list[dict[str, Any]]:
    """Messages as Responses API input items (the system prompt goes in ``instructions``)."""
    out: list[dict[str, Any]] = []
    for message in messages:
        texts = [p.text for p in message.content if isinstance(p, TextPart) and p.text]
        if message.role == Role.ASSISTANT:
            if texts:
                out.append({"role": "assistant", "content": "\n".join(texts)})
            out.extend(
                {
                    "type": "function_call",
                    "call_id": p.id,
                    "name": p.name,
                    "arguments": json.dumps(p.arguments),
                }
                for p in message.content
                if isinstance(p, ToolUsePart)
            )
            continue
        for part in message.content:
            if isinstance(part, ToolResultPart):
                content = f"ERROR: {part.content}" if part.is_error else part.content
                out.append(
                    {"type": "function_call_output", "call_id": part.tool_use_id, "output": content}
                )
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})
    return out


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        # Surface the malformed payload so input validation reports it to the model.
        return {"__invalid_json__": raw}
    return value if isinstance(value, dict) else {"value": value}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        preset: OpenAICompatPreset,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 600.0,
        client: Any | None = None,
        extra_params: dict[str, Any] | None = None,
        auth: str = "api_key",
    ) -> None:
        if auth not in AUTH_MODES:
            raise ConfigurationError(
                f"unknown auth mode '{auth}' for provider '{preset.name}' "
                f"(expected one of: {', '.join(AUTH_MODES)})"
            )
        self.name = preset.name
        self._preset = preset
        self._extra = dict(extra_params or {})
        self._proxy_auth = auth == "proxy"
        # Session id for requests that carry none (e.g. a one-off judge call):
        # one per provider instance, never one per HTTP request.
        self._default_session = uuid.uuid4().hex
        if client is not None:
            self._client = client
            return
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ConfigurationError(
                "the 'openai' package is required: pip install 'agentforge[openai]'"
            ) from exc
        if preset.requires_base_url and not (base_url or preset.base_url):
            raise ConfigurationError(
                f"provider '{preset.name}' requires model.base_url (its OpenAI-compatible endpoint)"
            )
        client_key: Any = api_key
        if self._proxy_auth:
            # The proxy adds the credential; the client holds none and sends none.
            client_key = _no_client_credential
        elif not api_key:
            if preset.requires_key:
                raise ConfigurationError(
                    f"no API key configured for provider '{preset.name}' "
                    f"(set {preset.api_key_env} or model.api_key_env)"
                )
            client_key = "not-required"  # local servers ignore the key
        self._client = openai.AsyncOpenAI(
            api_key=client_key,
            base_url=base_url or preset.base_url,
            max_retries=0,
            timeout=timeout_seconds,
        )

    def _headers(self, request: CompletionRequest) -> dict[str, Any]:
        """Per-request headers. Values are ids and a version, never credentials."""
        headers: dict[str, Any] = {}
        if self._preset.identify_client:
            headers["User-Agent"] = f"agentforge/{__version__}"
        if self._preset.session_header:
            headers[self._preset.session_header] = request.session_id or self._default_session
        if self._proxy_auth:
            import openai

            headers["Authorization"] = openai.Omit()
        return headers

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not request.model:
            raise ConfigurationError(f"provider '{self.name}' requires model.model to be set")
        api = self._preset.model_apis.get(request.model, "chat_completions")
        if api == "responses":
            return await self._complete_responses(request)
        if api != "chat_completions":
            raise LLMError(
                f"{self.name}: model '{request.model}' is served on the '{api}' endpoint, "
                "which this provider does not speak",
                retryable=False,
                code="unsupported_api",
            )
        params: dict[str, Any] = {
            "model": request.model,
            "messages": to_openai_messages(request.system, request.messages),
            self._preset.token_param: request.max_tokens,
        }
        if request.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in request.tools
            ]
        if request.temperature is not None:
            params["temperature"] = request.temperature
        params.update(self._extra)
        if headers := self._headers(request):
            params["extra_headers"] = {**params.get("extra_headers", {}), **headers}

        try:
            response = await self._client.chat.completions.create(**params)
        except Exception as exc:
            raise _translate_error(self.name, exc) from exc

        if not response.choices:
            raise LLMError(f"{self.name}: response contained no choices", retryable=True)
        choice = response.choices[0]
        msg = choice.message
        parts: list[ContentPart] = []
        if msg.content:
            parts.append(TextPart(text=msg.content))
        for call in msg.tool_calls or []:
            function = getattr(call, "function", None)
            if function is None:
                continue
            parts.append(
                ToolUsePart(
                    id=call.id, name=function.name, arguments=_parse_arguments(function.arguments)
                )
            )
        usage = response.usage
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        stop = _FINISH_REASONS.get(choice.finish_reason or "", StopReason.OTHER)
        if stop != StopReason.TOOL_USE and any(isinstance(p, ToolUsePart) for p in parts):
            stop = StopReason.TOOL_USE  # some local servers report "stop" with tool calls
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content=parts or [TextPart(text="")]),
            stop_reason=stop,
            raw_stop_reason=choice.finish_reason,
            usage=TokenUsage(
                input_tokens=(usage.prompt_tokens or 0) if usage else 0,
                output_tokens=(usage.completion_tokens or 0) if usage else 0,
                cache_read_tokens=cached,
            ),
            model=getattr(response, "model", None) or params["model"],
            response_id=getattr(response, "id", None),
        )

    async def _complete_responses(self, request: CompletionRequest) -> CompletionResponse:
        params: dict[str, Any] = {
            "model": request.model,
            "input": to_responses_input(request.messages),
            "max_output_tokens": request.max_tokens,
        }
        if request.system:
            params["instructions"] = request.system
        if request.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                }
                for t in request.tools
            ]
        if request.temperature is not None:
            params["temperature"] = request.temperature
        params.update(self._extra)
        if headers := self._headers(request):
            params["extra_headers"] = {**params.get("extra_headers", {}), **headers}

        try:
            response = await self._client.responses.create(**params)
        except Exception as exc:
            raise _translate_error(self.name, exc) from exc

        parts: list[ContentPart] = []
        for item in getattr(response, "output", None) or []:
            kind = getattr(item, "type", None)
            if kind == "message":
                text = "".join(
                    getattr(c, "text", "") or ""
                    for c in getattr(item, "content", None) or []
                    if getattr(c, "type", None) == "output_text"
                )
                if text:
                    parts.append(TextPart(text=text))
            elif kind == "function_call":
                parts.append(
                    ToolUsePart(
                        id=item.call_id, name=item.name, arguments=_parse_arguments(item.arguments)
                    )
                )
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) if details is not None else None
        if any(isinstance(p, ToolUsePart) for p in parts):
            stop = StopReason.TOOL_USE
        elif reason == "max_output_tokens":
            stop = StopReason.MAX_TOKENS
        elif reason == "content_filter":
            stop = StopReason.REFUSAL
        else:
            stop = StopReason.END_TURN
        usage = getattr(response, "usage", None)
        cached = 0
        cache_details = getattr(usage, "input_tokens_details", None) if usage else None
        if cache_details is not None:
            cached = getattr(cache_details, "cached_tokens", 0) or 0
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content=parts or [TextPart(text="")]),
            stop_reason=stop,
            raw_stop_reason=reason or getattr(response, "status", None),
            usage=TokenUsage(
                input_tokens=(getattr(usage, "input_tokens", 0) or 0) if usage else 0,
                output_tokens=(getattr(usage, "output_tokens", 0) or 0) if usage else 0,
                cache_read_tokens=cached,
            ),
            model=getattr(response, "model", None) or request.model,
            response_id=getattr(response, "id", None),
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


async def _no_client_credential() -> str:
    """Key provider for ``auth: proxy``: the client has no key (so sends no header)."""
    return ""


def _translate_error(provider: str, exc: Exception) -> LLMError:
    try:
        import openai
    except ImportError:  # pragma: no cover
        return LLMError(f"{provider} request failed: {type(exc).__name__}", retryable=False)

    if isinstance(exc, openai.APITimeoutError):
        return LLMError(f"{provider} request timed out", retryable=True, code="timeout")
    if isinstance(exc, openai.APIConnectionError):
        return LLMError(
            f"could not connect to {provider} endpoint", retryable=True, code="connection"
        )
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        retryable = status in (408, 409, 429) or status >= 500
        code = {401: "authentication", 403: "permission", 404: "not_found", 429: "rate_limit"}.get(
            status, "api_status"
        )
        return LLMError(
            f"{provider} API error {status}: {exc.message}",
            retryable=retryable,
            status_code=status,
            code=code,
        )
    return LLMError(f"{provider} request failed: {type(exc).__name__}: {exc}", retryable=False)
