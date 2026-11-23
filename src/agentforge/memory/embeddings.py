"""Text embeddings for vector memory search.

An :class:`Embedder` turns texts into vectors; :mod:`agentforge.memory.base`
ranks stored memories by cosine similarity to the query's vector.

Two embedders exist:

* :class:`HashingEmbedder` (here) - dependency-free and deterministic. It
  hashes words (without stopwords) and their character trigrams into a fixed
  number of buckets, so it
  matches on shared word *forms* ("configure" / "configuration") but knows
  nothing about meaning: "car" and "automobile" are unrelated to it. It is
  what tests and offline demos use, and a reasonable choice when no embedding
  model is available.
* :class:`agentforge.llm.embeddings.HttpEmbedder` - calls an
  OpenAI-compatible ``/embeddings`` endpoint, for semantic search with a real
  embedding model.

The embedder is chosen by the operator (``AGENTFORGE_MEMORY_EMBEDDER``), not
by an agent configuration, so a submitted agent can never direct memory
contents or a credential to an endpoint of its choosing.
"""

from __future__ import annotations

import hashlib
import math
import struct
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from agentforge.core.errors import AgentForgeError
from agentforge.memory.text import STOPWORDS, TOKEN

if TYPE_CHECKING:
    import httpx

    from agentforge.settings import Settings

#: Longest embedder name that fits the ``memory_embeddings.embedder`` column.
MAX_EMBEDDER_NAME = 128


class EmbeddingError(AgentForgeError):
    """An embedder could not produce vectors (network, credentials, bad response)."""

    code = "embedding_error"


class Embedder(ABC):
    """Turns texts into vectors.

    ``name`` identifies the vector space: vectors are stored under it and only
    compared with query vectors from an embedder of the same name, so changing
    the model (or the hashing dimensions) never mixes incompatible vectors.
    """

    name: str

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per text, in order. Raises :class:`EmbeddingError`."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release resources (HTTP connections). Default: nothing to release."""


class HashingEmbedder(Embedder):
    """Signed feature hashing over words and character trigrams (lexical, offline)."""

    #: Bumped when the feature scheme changes, so old vectors are not reused.
    SCHEME = "hashing-v1"

    def __init__(self, dimensions: int = 256) -> None:
        if not 64 <= dimensions <= 4096:
            raise ValueError("hashing embedder dimensions must be between 64 and 4096")
        self.dimensions = dimensions
        self.name = f"{self.SCHEME}:{dimensions}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]

    def embed_one(self, text: str) -> list[float]:
        features: dict[str, float] = {}
        for word in TOKEN.findall(text.lower()):
            if word in STOPWORDS:
                continue
            features[f"w:{word}"] = features.get(f"w:{word}", 0.0) + 1.0
            padded = f"^{word}$"
            for i in range(len(padded) - 2):
                gram = f"g:{padded[i : i + 3]}"
                features[gram] = features.get(gram, 0.0) + 0.5
        vector = [0.0] * self.dimensions
        for feature, count in features.items():
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            sign = 1.0 if value & 1 else -1.0
            vector[(value >> 1) % self.dimensions] += sign * math.sqrt(count)
        return normalize(vector)


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 for a zero vector or mismatched lengths."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def pack_vector(vector: list[float]) -> bytes:
    """Serialise as little-endian float32 (4 bytes per dimension)."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> list[float]:
    if len(blob) % 4:
        raise ValueError("vector blob length is not a multiple of 4")
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def build_embedder(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> Embedder | None:
    """The embedder the operator configured, or ``None`` (lexical search only)."""
    kind = settings.memory_embedder
    if kind == "none":
        return None
    if kind == "hashing":
        return HashingEmbedder(settings.embedding_dimensions)
    from agentforge.llm.embeddings import HttpEmbedder

    return HttpEmbedder.from_settings(settings, transport=transport)
