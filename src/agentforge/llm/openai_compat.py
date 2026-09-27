"""OpenAI Chat Completions adapter (official ``openai`` SDK).

The Chat Completions wire format is the de-facto standard for many endpoints,
so this one adapter serves several provider presets:

* ``openai``      - api.openai.com
* ``openrouter``  - openrouter.ai (hundreds of hosted models)
* ``gemini``      - Google's OpenAI-compatible Gemini endpoint
* ``local``       - any local OpenAI-compatible server (Ollama, vLLM, LM Studio,
  llama.cpp server); defaults to Ollama's address.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

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
    ),
    "local": OpenAICompatPreset(
        name="local",
        base_url="http://localhost:11434/v1",
        api_key_env=None,
        requires_key=False,
    ),
}

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
    ) -> None:
        self.name = preset.name
        self._preset = preset
        self._extra = dict(extra_params or {})
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
        if not api_key:
            if preset.requires_key:
                raise ConfigurationError(
                    f"no API key configured for provider '{preset.name}' "
                    f"(set {preset.api_key_env} or model.api_key_env)"
                )
            api_key = "not-required"  # local servers ignore the key
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or preset.base_url,
            max_retries=0,
            timeout=timeout_seconds,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not request.model:
            raise ConfigurationError(f"provider '{self.name}' requires model.model to be set")
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

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


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
