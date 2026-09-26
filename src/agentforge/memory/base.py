"""Memory abstraction.

Three scopes are supported:

* ``run``   - short-term execution memory for a single run (the conversation
  window itself is managed by :mod:`agentforge.memory.context`);
* ``task``  - notes shared by runs working on the same task key (e.g. a
  benchmark task or GitHub issue);
* ``agent`` - persistent memory for an agent across all of its runs.

The default search is a dependency-free lexical scorer. The interface is kept
small so a vector store can implement it later (``search`` receives the raw
query and returns ranked records).
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentforge.core.ids import new_id, utcnow


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


_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def lexical_rank(query: str, records: list[MemoryRecord], limit: int) -> list[ScoredMemory]:
    """Rank records with a small BM25-style scorer over content and tags."""
    query_terms = tokenize(query)
    if not query_terms or not records:
        return []
    docs = [tokenize(r.content + " " + " ".join(r.tags)) for r in records]
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


class MemoryStore(ABC):
    @abstractmethod
    async def add(self, record: MemoryRecord) -> MemoryRecord: ...

    @abstractmethod
    async def list_records(
        self, scope: MemoryScope, namespace: str, *, limit: int = 100
    ) -> list[MemoryRecord]: ...

    @abstractmethod
    async def delete(self, record_id: str) -> bool: ...

    async def search(
        self, scope: MemoryScope, namespace: str, query: str, *, limit: int = 5
    ) -> list[ScoredMemory]:
        records = await self.list_records(scope, namespace, limit=1_000)
        return lexical_rank(query, records, limit)


class InMemoryMemoryStore(MemoryStore):
    """Process-local store (tests, CLI one-off runs)."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

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
        return self._records.pop(record_id, None) is not None
