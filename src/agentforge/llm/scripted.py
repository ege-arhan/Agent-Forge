"""Deterministic scripted provider.

The scripted provider replays a pre-written sequence of model turns. It exists
so that the runtime, tools, evaluation and benchmark pipelines can be exercised
end-to-end offline and in CI. It reports zero token usage and is *not* a model:
results obtained with it say nothing about any real model's capability.

Script format (``ModelConfig.options``)::

    turns:                       # used when no rule matches
      - text: "Let me look around."
        tool_calls:
          - name: list_directory
            arguments: {path: "."}
      - text: "Done."
    rules:                       # optional: pick a script by matching the goal
      - when: "hello\\.txt"      # regular expression searched in the first user message
        turns: [...]
    on_exhausted: finish         # finish (default) | error

A turn may also be ``{error: {message: "...", retryable: true}}`` to simulate
provider failures.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

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
    ToolUsePart,
)


class ScriptedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ScriptedError(BaseModel):
    message: str = "scripted failure"
    retryable: bool = True


class ScriptedTurn(BaseModel):
    text: str = ""
    tool_calls: list[ScriptedToolCall] = Field(default_factory=list)
    error: ScriptedError | None = None


class ScriptRule(BaseModel):
    when: str
    turns: list[ScriptedTurn]


class Script(BaseModel):
    turns: list[ScriptedTurn] = Field(default_factory=list)
    rules: list[ScriptRule] = Field(default_factory=list)
    on_exhausted: str = "finish"


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, script: Script) -> None:
        self._script = script
        # Position is tracked per conversation (keyed by the first user message)
        # so one provider instance can serve several independent runs.
        self._positions: dict[str, int] = {}

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> ScriptedProvider:
        try:
            return cls(Script.model_validate(options))
        except ValueError as exc:
            raise ConfigurationError(f"invalid scripted provider options: {exc}") from exc

    def _select_turns(self, first_user_text: str) -> list[ScriptedTurn]:
        for rule in self._script.rules:
            if re.search(rule.when, first_user_text):
                return rule.turns
        return self._script.turns

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        first_user = next((m for m in request.messages if m.role == Role.USER), None)
        key = first_user.text if first_user else ""
        turns = self._select_turns(key)
        # The number of assistant turns already in the conversation tells us
        # where we are; this keeps replay stable across retries.
        position = sum(1 for m in request.messages if m.role == Role.ASSISTANT)
        position += self._positions.get(key, 0)

        if position >= len(turns):
            if self._script.on_exhausted == "error":
                raise LLMError("scripted provider: script exhausted", retryable=False)
            return self._response(
                Message(role=Role.ASSISTANT, content=[TextPart(text="Script exhausted.")]),
                request,
            )

        turn = turns[position]
        if turn.error is not None:
            # Consume the error turn so a retry proceeds to the next scripted turn.
            self._positions[key] = self._positions.get(key, 0) + 1
            raise LLMError(turn.error.message, retryable=turn.error.retryable)

        parts: list[ContentPart] = []
        if turn.text:
            parts.append(TextPart(text=turn.text))
        for index, call in enumerate(turn.tool_calls):
            parts.append(
                ToolUsePart(id=f"call_{position}_{index}", name=call.name, arguments=call.arguments)
            )
        if not parts:
            parts.append(TextPart(text=""))
        return self._response(Message(role=Role.ASSISTANT, content=parts), request)

    def _response(self, message: Message, request: CompletionRequest) -> CompletionResponse:
        stop = StopReason.TOOL_USE if message.tool_uses else StopReason.END_TURN
        return CompletionResponse(
            message=message,
            stop_reason=stop,
            usage=TokenUsage(),
            model=request.model or "scripted",
            raw_stop_reason=stop.value,
        )
