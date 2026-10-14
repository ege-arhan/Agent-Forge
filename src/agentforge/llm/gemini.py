"""Google Gemini native adapter (``generativelanguage.googleapis.com``).

Speaks the Gemini API's own ``generateContent`` wire format directly over
``httpx`` (a core dependency), so no vendor SDK or optional extra is needed -
unlike the ``gemini`` preset this replaces, which went through the OpenAI
Chat Completions compatibility shim (``llm/openai_compat.py``).

Two differences from Anthropic/OpenAI drive the translation below:

* Roles are ``user``/``model`` (not ``assistant``), and the system prompt is
  a separate ``systemInstruction`` field, not a message.
* A function call carries no id: ``functionResponse`` matches it by ``name``
  alone. An id is synthesised for :class:`ToolUsePart` on the way out of the
  API and resolved back to a name (via a running map built while walking the
  conversation) for ``functionResponse`` on the way in.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

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
    ToolSpec,
    ToolUsePart,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# A header, never the API's ``?key=`` query string, keeps the credential out
# of URLs (request logs, proxies, browser history equivalents).
API_KEY_HEADER = "x-goog-api-key"

_FINISH_REASONS = {
    "STOP": StopReason.END_TURN,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "SAFETY": StopReason.REFUSAL,
    "RECITATION": StopReason.REFUSAL,
    "BLOCKLIST": StopReason.REFUSAL,
    "PROHIBITED_CONTENT": StopReason.REFUSAL,
    "SPII": StopReason.REFUSAL,
    "IMAGE_SAFETY": StopReason.REFUSAL,
}


def to_gemini_contents(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate neutral messages to Gemini ``contents``."""
    call_names: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for message in messages:
        parts: list[dict[str, Any]] = []
        for part in message.content:
            if isinstance(part, TextPart):
                if part.text:
                    parts.append({"text": part.text})
            elif isinstance(part, ToolUsePart):
                call_names[part.id] = part.name
                parts.append({"functionCall": {"name": part.name, "args": part.arguments}})
            elif isinstance(part, ToolResultPart):
                name = call_names.get(part.tool_use_id, part.tool_use_id)
                response = {"error": part.content} if part.is_error else {"output": part.content}
                parts.append({"functionResponse": {"name": name, "response": response}})
            elif isinstance(part, ProviderPart) and part.provider == GeminiProvider.name:
                parts.append(part.data)
        if not parts:
            parts.append({"text": "(empty)"})
        out.append({"role": "model" if message.role == Role.ASSISTANT else "user", "parts": parts})
    return out


def from_gemini_parts(parts: list[dict[str, Any]]) -> list[ContentPart]:
    """Translate a Gemini candidate's ``content.parts`` to neutral content.

    A "thought" part (extended-thinking models) is preserved unchanged as an
    opaque :class:`ProviderPart` so it can be echoed back on the next turn,
    the same way ``llm/anthropic.py`` handles Anthropic's ``thinking`` blocks.
    """
    result: list[ContentPart] = []
    for part in parts:
        if part.get("thought"):
            result.append(ProviderPart(provider=GeminiProvider.name, data=part))
        elif "functionCall" in part:
            call = part["functionCall"]
            args = call.get("args")
            if not isinstance(args, dict):
                args = {} if args is None else {"value": args}
            result.append(
                ToolUsePart(id=f"call_{uuid.uuid4().hex[:12]}", name=call["name"], arguments=args)
            )
        elif "text" in part:
            result.append(TextPart(text=part.get("text") or ""))
        else:
            result.append(ProviderPart(provider=GeminiProvider.name, data=part))
    return result


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 600.0,
        client: httpx.AsyncClient | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        self._extra = dict(extra_params or {})
        if client is not None:
            self._client = client
            return
        if not api_key:
            raise ConfigurationError(
                "no Gemini API key configured (set GEMINI_API_KEY or model.api_key_env)"
            )
        self._client = httpx.AsyncClient(
            base_url=base_url or DEFAULT_BASE_URL,
            headers={API_KEY_HEADER: api_key},
            timeout=timeout_seconds,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not request.model:
            raise ConfigurationError("provider 'gemini' requires model.model to be set")
        body: dict[str, Any] = {"contents": to_gemini_contents(request.messages)}
        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}
        if request.tools:
            body["tools"] = [{"functionDeclarations": [_declaration(t) for t in request.tools]}]
        generation_config: dict[str, Any] = {"maxOutputTokens": request.max_tokens}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        body["generationConfig"] = generation_config
        body.update(self._extra)

        try:
            response = await self._client.post(
                f"/models/{request.model}:generateContent", json=body
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _translate_status_error(exc) from exc
        except httpx.TimeoutException as exc:
            raise LLMError("gemini request timed out", retryable=True, code="timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"could not connect to Gemini API: {type(exc).__name__}",
                retryable=True,
                code="connection",
            ) from exc

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("gemini: response contained no candidates", retryable=True)
        candidate = candidates[0]
        parts = from_gemini_parts((candidate.get("content") or {}).get("parts") or [])
        raw_finish = candidate.get("finishReason")
        stop = _FINISH_REASONS.get(raw_finish or "", StopReason.OTHER)
        if any(isinstance(p, ToolUsePart) for p in parts):
            stop = StopReason.TOOL_USE
        usage = data.get("usageMetadata") or {}
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content=parts or [TextPart(text="")]),
            stop_reason=stop,
            raw_stop_reason=raw_finish,
            usage=TokenUsage(
                input_tokens=usage.get("promptTokenCount", 0) or 0,
                output_tokens=usage.get("candidatesTokenCount", 0) or 0,
                cache_read_tokens=usage.get("cachedContentTokenCount", 0) or 0,
            ),
            model=data.get("modelVersion") or request.model,
            response_id=data.get("responseId"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _declaration(tool: ToolSpec) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}


def _translate_status_error(exc: httpx.HTTPStatusError) -> LLMError:
    status = exc.response.status_code
    try:
        message = exc.response.json().get("error", {}).get("message") or exc.response.text
    except ValueError:
        message = exc.response.text
    retryable = status in (408, 409, 429) or status >= 500
    code = {401: "authentication", 403: "permission", 404: "not_found", 429: "rate_limit"}.get(
        status, "api_status"
    )
    # message comes from the API response body, never from our credentials.
    return LLMError(
        f"gemini API error {status}: {message}", retryable=retryable, status_code=status, code=code
    )
