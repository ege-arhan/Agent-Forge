"""Anthropic Messages API adapter (official ``anthropic`` SDK)."""

from __future__ import annotations

from typing import Any

from agentforge.core.errors import ConfigurationError, LLMError
from agentforge.core.models import TokenUsage
from agentforge.llm.base import LLMProvider
from agentforge.llm.types import (
    CompletionRequest,
    CompletionResponse,
    ContentPart,
    Message,
    ProviderPart,
    Role,
    StopReason,
    TextPart,
    ToolResultPart,
    ToolUsePart,
)

DEFAULT_MODEL = "claude-opus-5"

_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}

# Block types that must be echoed back unchanged on the next request.
_OPAQUE_BLOCKS = {"thinking", "redacted_thinking"}


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate neutral messages to Messages API ``messages``."""
    out: list[dict[str, Any]] = []
    for message in messages:
        blocks: list[dict[str, Any]] = []
        for part in message.content:
            if isinstance(part, TextPart):
                if part.text:
                    blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, ToolUsePart):
                blocks.append(
                    {"type": "tool_use", "id": part.id, "name": part.name, "input": part.arguments}
                )
            elif isinstance(part, ToolResultPart):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": part.tool_use_id,
                        "content": part.content,
                        "is_error": part.is_error,
                    }
                )
            elif part.provider == AnthropicProvider.name:
                blocks.append(part.data)
        if not blocks:
            blocks.append({"type": "text", "text": "(empty)"})
        out.append({"role": message.role.value, "content": blocks})
    return out


def from_anthropic_content(blocks: list[Any]) -> list[ContentPart]:
    parts: list[ContentPart] = []
    for block in blocks:
        data = block.model_dump() if hasattr(block, "model_dump") else dict(block)
        kind = data.get("type")
        if kind == "text":
            parts.append(TextPart(text=data.get("text", "")))
        elif kind == "tool_use":
            arguments = data.get("input") or {}
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
            parts.append(ToolUsePart(id=data["id"], name=data["name"], arguments=arguments))
        elif kind in _OPAQUE_BLOCKS:
            parts.append(ProviderPart(provider=AnthropicProvider.name, data=data))
    return parts


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 600.0,
        client: Any | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        self._extra = dict(extra_params or {})
        if client is not None:
            self._client = client
            return
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ConfigurationError(
                "the 'anthropic' package is required: pip install 'agentforge[anthropic]'"
            ) from exc
        if not api_key:
            raise ConfigurationError(
                "no Anthropic API key configured (set ANTHROPIC_API_KEY or model.api_key_env)"
            )
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=0, timeout=timeout_seconds
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        params: dict[str, Any] = {
            "model": request.model or DEFAULT_MODEL,
            "max_tokens": request.max_tokens,
            "messages": to_anthropic_messages(request.messages),
        }
        if request.system:
            params["system"] = request.system
        if request.tools:
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in request.tools
            ]
        if request.temperature is not None:
            params["temperature"] = request.temperature
        params.update(self._extra)

        try:
            response = await self._client.messages.create(**params)
        except Exception as exc:
            raise _translate_error(exc) from exc

        usage = getattr(response, "usage", None)
        token_usage = TokenUsage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
        raw_stop = getattr(response, "stop_reason", None)
        return CompletionResponse(
            message=Message(
                role=Role.ASSISTANT, content=from_anthropic_content(list(response.content))
            ),
            stop_reason=_STOP_REASONS.get(raw_stop or "", StopReason.OTHER),
            raw_stop_reason=raw_stop,
            usage=token_usage,
            model=getattr(response, "model", params["model"]),
            response_id=getattr(response, "id", None),
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


def _translate_error(exc: Exception) -> LLMError:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return LLMError(f"anthropic request failed: {type(exc).__name__}", retryable=False)

    if isinstance(exc, anthropic.APITimeoutError):
        return LLMError("anthropic request timed out", retryable=True, code="timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("could not connect to Anthropic API", retryable=True, code="connection")
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        retryable = status in (408, 409, 429) or status >= 500
        code = {401: "authentication", 403: "permission", 404: "not_found", 429: "rate_limit"}.get(
            status, "api_status"
        )
        # exc.message comes from the API response body, never from our credentials.
        return LLMError(
            f"anthropic API error {status}: {exc.message}",
            retryable=retryable,
            status_code=status,
            code=code,
        )
    return LLMError(f"anthropic request failed: {type(exc).__name__}: {exc}", retryable=False)
