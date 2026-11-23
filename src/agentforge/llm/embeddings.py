"""Embeddings over an OpenAI-compatible ``/embeddings`` endpoint.

Speaks the wire format directly over ``httpx`` (no vendor SDK), so it works
with OpenAI, OpenRouter and local servers (Ollama, vLLM, llama.cpp, LM Studio)
that expose the same route::

    POST {base_url}/embeddings   {"model": "...", "input": ["...", "..."]}
    -> {"data": [{"index": 0, "embedding": [...]}, ...]}

Configured by the operator through ``AGENTFORGE_EMBEDDING_*`` settings (see
:func:`agentforge.memory.embeddings.build_embedder`). Not yet run against a
live endpoint: it is tested with a mocked transport only.
"""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any

import httpx

from agentforge.core.errors import ConfigurationError
from agentforge.memory.embeddings import MAX_EMBEDDER_NAME, Embedder, EmbeddingError

if TYPE_CHECKING:
    from agentforge.settings import Settings

#: Texts per request.
BATCH_SIZE = 64
#: Characters of each text that are sent (embedding models have token limits;
#: memory records are capped at 5 000 characters by the ``remember`` tool).
MAX_TEXT_CHARS = 8_000


class HttpEmbedder(Embedder):
    def __init__(
        self,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not model.strip():
            raise ConfigurationError("an embedding model name is required")
        # The endpoint is part of the vector space's identity: two servers may
        # serve different models under one name, and their vectors must not mix.
        name = f"openai-compatible:{model}@{_endpoint_id(base_url)}"
        if len(name) > MAX_EMBEDDER_NAME:
            raise ConfigurationError(
                "the embedding model name and endpoint are too long together "
                f"(over {MAX_EMBEDDER_NAME - len('openai-compatible:@')} characters)"
            )
        self.model = model
        self.name = name
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> HttpEmbedder:
        if not settings.embedding_model:
            raise ConfigurationError(
                "AGENTFORGE_MEMORY_EMBEDDER=openai-compatible needs AGENTFORGE_EMBEDDING_MODEL"
            )
        api_key: str | None = None
        if settings.embedding_api_key_env:
            api_key = os.environ.get(settings.embedding_api_key_env) or None
            if api_key is None:
                raise ConfigurationError(
                    f"the embedding credential {settings.embedding_api_key_env} is not set "
                    "(set AGENTFORGE_EMBEDDING_API_KEY_ENV to an empty value for an "
                    "endpoint that needs no key)"
                )
        return cls(
            settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=api_key,
            transport=transport,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + BATCH_SIZE]))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        # An empty string is rejected by several servers; a space embeds fine.
        payload = {"model": self.model, "input": [t[:MAX_TEXT_CHARS] or " " for t in texts]}
        try:
            response = await self._client.post("embeddings", json=payload)
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise EmbeddingError(
                f"embedding endpoint returned HTTP {response.status_code}{_error_detail(response)}"
            )
        try:
            return _parse(response.json(), expected=len(texts))
        except ValueError as exc:
            raise EmbeddingError(f"embedding endpoint returned an invalid response: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _endpoint_id(base_url: str) -> str:
    """Host, port and path of the endpoint (no scheme, no credentials), lower-cased host."""
    try:
        url = httpx.URL(base_url)
    except httpx.InvalidURL as exc:
        raise ConfigurationError("the embedding base URL is not a valid URL") from exc
    if not url.host:
        raise ConfigurationError("the embedding base URL is not a valid URL")
    port = f":{url.port}" if url.port is not None else ""
    return f"{url.host.lower()}{port}{url.path.rstrip('/')}"


def _error_detail(response: httpx.Response) -> str:
    """The server's error message, shortened. Never the request (texts, key)."""
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    if not isinstance(message, str) or not message:
        return ""
    return f": {message[:200]}"


def _parse(body: Any, *, expected: int) -> list[list[float]]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or len(data) != expected:
        raise ValueError(f"expected {expected} embeddings")
    vectors: list[list[float] | None] = [None] * expected
    for position, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError("an embedding entry is not an object")
        index = item.get("index", position)
        embedding = item.get("embedding")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < expected:
            raise ValueError("an embedding index is out of range")
        if vectors[index] is not None:
            raise ValueError("an embedding index is repeated")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("an embedding is not a list of numbers")
        vector: list[float] = []
        for value in embedding:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("an embedding is not a list of numbers")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("an embedding contains a non-finite number")
            vector.append(number)
        vectors[index] = vector
    result = [v for v in vectors if v is not None]
    if len({len(v) for v in result}) != 1:
        raise ValueError("embeddings have different dimensions")
    return result
