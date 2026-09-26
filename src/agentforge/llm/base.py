"""LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentforge.llm.types import CompletionRequest, CompletionResponse


class LLMProvider(ABC):
    """A chat-completion capable model endpoint.

    Implementations must:

    * translate :class:`CompletionRequest` to the vendor wire format and back;
    * raise :class:`agentforge.core.errors.LLMError` for every failure, with
      ``retryable`` set for transient conditions (rate limits, 5xx, network);
    * never log or embed API keys in error messages.

    Retries are owned by the runtime (see ``RetryPolicy``), so adapters should
    disable any SDK-level automatic retries to keep attempt counts accurate.
    """

    #: Stable provider identifier used in configs, records and pricing lookups.
    name: str = "base"

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Run a single completion."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release network resources held by the provider."""
