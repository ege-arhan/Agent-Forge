"""Provider-neutral chat types.

Every provider adapter translates between these types and its own wire format,
so the runtime never depends on a specific vendor API.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from agentforge.core.models import TokenUsage


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUsePart(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultPart(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


class ProviderPart(BaseModel):
    """An opaque provider-specific block (e.g. a reasoning/thinking block).

    Some APIs require such blocks to be sent back unchanged on the next turn.
    Adapters echo parts whose ``provider`` matches their own name and drop the
    rest, so conversations remain portable across providers.
    """

    type: Literal["provider"] = "provider"
    provider: str
    data: dict[str, Any]


ContentPart = Annotated[
    TextPart | ToolUsePart | ToolResultPart | ProviderPart, Field(discriminator="type")
]


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """A conversation turn. Tool results travel in ``user`` messages."""

    role: Role
    content: list[ContentPart]

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role=Role.USER, content=[TextPart(text=text)])

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role=Role.ASSISTANT, content=[TextPart(text=text)])

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.content if isinstance(p, TextPart))

    @property
    def tool_uses(self) -> list[ToolUsePart]:
        return [p for p in self.content if isinstance(p, ToolUsePart)]


class ToolSpec(BaseModel):
    """Tool definition as exposed to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    OTHER = "other"


class CompletionRequest(BaseModel):
    model: str
    system: str | None = None
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    max_tokens: int = 4096
    temperature: float | None = None
    # Stable id of the conversation this request belongs to (the run id), for
    # providers that route or cache per session. Not a credential.
    session_id: str | None = None


class CompletionResponse(BaseModel):
    message: Message
    stop_reason: StopReason
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str
    raw_stop_reason: str | None = None
    response_id: str | None = None
