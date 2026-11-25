"""Memory abstraction.

Three scopes are supported:

* ``run``   - short-term execution memory for a single run (the conversation
  window itself is managed by :mod:`agentforge.memory.context`);
* ``task``  - notes shared by runs working on the same task key (e.g. a
  benchmark task or GitHub issue);
* ``agent`` - persistent memory for an agent across all of its runs.

Search has three modes (:class:`agentforge.core.config.MemorySearchMode`):

* ``lexical`` (default) - a dependency-free BM25-style scorer;
* ``vector`` - cosine similarity between the query's embedding and each
  record's, needing an :class:`~agentforge.memory.embeddings.Embedder`;
* ``hybrid`` - both rankings combined by reciprocal rank fusion.

Vector search is brute force: the most recent :data:`SEARCH_WINDOW` records of
the namespace are scored in Python. There is no approximate index, which is
adequate for per-agent memories of this size and nothing more. Records get
their embedding the first time a vector search sees them (and are re-embedded
when the embedder changes), so memories written before an embedder was
configured are searchable without a migration step. If the embedder is missing
or fails, the search falls back to the lexical ranking instead of failing the
run.

A score's meaning depends on the mode: a BM25 score (lexical), a cosine
similarity in [-1, 1] (vector) or a fusion score (hybrid). Scores from
different modes are not comparable.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentforge.core.config import MemorySearchMode
from agentforge.core.ids import new_id, utcnow
from agentforge.memory.embeddings import Embedder, EmbeddingError, cosine
from agentforge.memory.text import tokenize

logger = logging.getLogger("agentforge.memory")

#: Records of a namespace considered by one search (most recent first).
SEARCH_WINDOW = 1_000
#: Reciprocal rank fusion constant (Cormack et al., 2009).
RRF_K = 60


class MemoryScope(StrEnum):
    RUN = "run"
    TASK = "task"
    AGENT = "agent"


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    scope: MemoryScope
    namespace: str = Field(description="Run id, task key or agent id depending on scope.")
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ScoredMemory(BaseModel):
    record: MemoryRecord
    score: float


def lexical_rank(query: str, records: list[MemoryRecord], limit: int) -> list[ScoredMemory]:
    """Rank records with a small BM25-style scorer over content and tags."""
    query_terms = tokenize(query)
    if not query_terms or not records:
        return []
    docs = [tokenize(record_text(r)) for r in records]
    n_docs = len(docs)
    avg_len = sum(len(d) for d in docs) / n_docs or 1.0
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    k1, b = 1.5, 0.75
    scored: list[ScoredMemory] = []
    for record, doc in zip(records, docs, strict=True):
        tf = Counter(doc)
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(doc) / avg_len))
        if score > 0:
            scored.append(ScoredMemory(record=record, score=round(score, 6)))
    scored.sort(key=lambda s: (-s.score, s.record.created_at), reverse=False)
    return scored[:limit]


def record_text(record: MemoryRecord) -> str:
    """The text of a record that is searched (lexically) and embedded."""
    return (record.content + " " + " ".join(record.tags)).strip()


def vector_rank(
    query_vector: list[float],
    candidates: list[tuple[MemoryRecord, list[float]]],
    limit: int,
    *,
    min_similarity: float = 0.0,
) -> list[ScoredMemory]:
    """Rank records by cosine similarity, keeping those above ``min_similarity``."""
    scored = [
        ScoredMemory(record=record, score=round(similarity, 6))
        for record, vector in candidates
        if (similarity := cosine(query_vector, vector)) > min_similarity
    ]
    scored.sort(key=lambda s: (-s.score, s.record.created_at))
    return scored[:limit]


def reciprocal_rank_fusion(rankings: list[list[ScoredMemory]], limit: int) -> list[ScoredMemory]:
    """Combine rankings: a record scores ``sum(1 / (RRF_K + rank))`` over the lists it is in."""
    scores: dict[str, float] = {}
    records: dict[str, MemoryRecord] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.record.id] = scores.get(hit.record.id, 0.0) + 1.0 / (RRF_K + rank)
            records[hit.record.id] = hit.record
    fused = [
        ScoredMemory(record=records[record_id], score=round(score, 6))
        for record_id, score in scores.items()
    ]
    fused.sort(key=lambda s: (-s.score, s.record.created_at))
    return fused[:limit]


class MemoryStore(ABC):
    #: Set to enable ``vector`` and ``hybrid`` search.
    embedder: Embedder | None = None
    _warned_no_embedder: bool = False

    @abstractmethod
    async def add(self, record: MemoryRecord) -> MemoryRecord: ...

    @abstractmethod
    async def list_records(
        self, scope: MemoryScope, namespace: str, *, limit: int = 100
    ) -> list[MemoryRecord]: ...

    @abstractmethod
    async def delete(self, record_id: str) -> bool: ...

    async def search(
        self,
        scope: MemoryScope,
        namespace: str,
        query: str,
        *,
        limit: int = 5,
        mode: MemorySearchMode | str = MemorySearchMode.LEXICAL,
        min_similarity: float = 0.0,
    ) -> list[ScoredMemory]:
        mode = MemorySearchMode(mode)
        records = await self.list_records(scope, namespace, limit=SEARCH_WINDOW)
        if mode is MemorySearchMode.LEXICAL or not records or limit <= 0:
            return lexical_rank(query, records, limit)
        if self.embedder is None:
            if not self._warned_no_embedder:
                self._warned_no_embedder = True
                logger.warning(
                    "memory search mode %r requested but no embedder is configured "
                    "(AGENTFORGE_MEMORY_EMBEDDER); using lexical search",
                    mode.value,
                )
            return lexical_rank(query, records, limit)
        try:
            candidates, query_vector = await self._embedded(self.embedder, records, query)
        except EmbeddingError as exc:
            logger.warning("memory embedding failed (%s); using lexical search", exc.message)
            return lexical_rank(query, records, limit)
        semantic = vector_rank(
            query_vector, candidates, len(candidates), min_similarity=min_similarity
        )
        if mode is MemorySearchMode.VECTOR:
            return semantic[:limit]
        lexical = lexical_rank(query, records, len(records))
        return reciprocal_rank_fusion([lexical, semantic], limit)

    async def _embedded(
        self, embedder: Embedder, records: list[MemoryRecord], query: str
    ) -> tuple[list[tuple[MemoryRecord, list[float]]], list[float]]:
        """Vectors for ``records`` (embedding and storing the missing ones) and the query."""
        (query_vector,) = await embedder.embed([query])
        stored = await self._load_vectors([r.id for r in records], embedder.name)
        # A stored vector of another length cannot be compared: embed it again.
        missing = [r for r in records if len(stored.get(r.id, ())) != len(query_vector)]
        if missing:
            fresh = await embedder.embed([record_text(r) for r in missing])
            if len(fresh) != len(missing):
                raise EmbeddingError("the embedder returned the wrong number of vectors")
            new = {r.id: vector for r, vector in zip(missing, fresh, strict=True)}
            stored.update(new)
            try:
                await self._save_vectors(new, embedder.name)
            except Exception:  # the search result does not depend on the cache
                logger.exception("failed to store %d memory embeddings", len(new))
        return [(r, stored[r.id]) for r in records], query_vector

    async def _load_vectors(self, record_ids: list[str], embedder: str) -> dict[str, list[float]]:
        """Stored vectors by record id. Default: none (every search embeds every record)."""
        return {}

    async def _save_vectors(self, vectors: dict[str, list[float]], embedder: str) -> None:  # noqa: B027
        """Persist vectors for later searches. Default: not stored."""


class InMemoryMemoryStore(MemoryStore):
    """Process-local store (tests, CLI one-off runs)."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder
        self._records: dict[str, MemoryRecord] = {}
        self._vectors: dict[tuple[str, str], list[float]] = {}

    async def add(self, record: MemoryRecord) -> MemoryRecord:
        self._records[record.id] = record
        return record

    async def list_records(
        self, scope: MemoryScope, namespace: str, *, limit: int = 100
    ) -> list[MemoryRecord]:
        matches = [
            r for r in self._records.values() if r.scope == scope and r.namespace == namespace
        ]
        matches.sort(key=lambda r: r.created_at, reverse=True)
        return matches[:limit]

    async def delete(self, record_id: str) -> bool:
        for key in [k for k in self._vectors if k[0] == record_id]:
            del self._vectors[key]
        return self._records.pop(record_id, None) is not None

    async def _load_vectors(self, record_ids: list[str], embedder: str) -> dict[str, list[float]]:
        return {
            record_id: self._vectors[record_id, embedder]
            for record_id in record_ids
            if (record_id, embedder) in self._vectors
        }

    async def _save_vectors(self, vectors: dict[str, list[float]], embedder: str) -> None:
        for record_id, vector in vectors.items():
            if record_id in self._records:
                self._vectors[record_id, embedder] = vector
