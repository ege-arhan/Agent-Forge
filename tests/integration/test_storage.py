from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from agentforge.core.errors import NotFoundError
from agentforge.core.models import EvaluationResult, Run, RunMetrics, RunStatus, TokenUsage
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.memory.base import MemoryRecord, MemoryScope
from agentforge.memory.embeddings import Embedder, HashingEmbedder
from agentforge.runtime.factory import prepare_run
from agentforge.settings import Settings
from agentforge.storage import (
    AgentRepository,
    Database,
    PersistenceObserver,
    RunRepository,
    SqlMemoryStore,
)
from agentforge.storage.db import MemoryEmbeddingRow
from tests.conftest import scripted_config

pytestmark = pytest.mark.integration


async def test_agent_crud(db: Database) -> None:
    repo = AgentRepository(db)
    config = scripted_config([], name="alpha")
    agent = await repo.create(config)
    assert (await repo.get(agent.id)).config == config
    with pytest.raises(ValueError, match="already exists"):
        await repo.create(config)
    updated = await repo.update(agent.id, config.model_copy(update={"description": "new"}))
    assert updated.version == 2 and updated.config.description == "new"
    assert [a.name for a in await repo.list()] == ["alpha"]
    assert (await repo.get_by_name("alpha")) is not None
    await repo.delete(agent.id)
    with pytest.raises(NotFoundError):
        await repo.get(agent.id)


async def test_run_persisted_live_and_final(db: Database, settings: Settings) -> None:
    runs = RunRepository(db)
    turns = [
        {"tool_calls": [{"name": "write_file", "arguments": {"path": "a.txt", "content": "x"}}]},
        {"tool_calls": [{"name": "read_file", "arguments": {"path": "missing.txt"}}]},
        {"text": "done"},
    ]
    prepared = prepare_run(
        scripted_config(turns), "goal", settings=settings, observers=[PersistenceObserver(runs)]
    )
    run = await prepared.execute([EvaluatorSpec(type="file_exists", path="a.txt")])
    stored = await runs.get(run.id)
    assert stored.status == RunStatus.SUCCEEDED
    assert stored.model_dump() == run.model_dump()

    page = await runs.list(status=RunStatus.SUCCEEDED)
    assert page.total == 1 and page.items[0].id == run.id
    stats = await runs.stats()
    assert stats["total_runs"] == 1
    assert stats["evaluation_pass_rate"] == 1.0
    assert stats["tool_calls"]["write_file"] == {"success": 1}
    assert stats["tool_calls"]["read_file"] == {"error": 1}


async def test_mark_interrupted(db: Database, settings: Settings) -> None:
    runs = RunRepository(db)
    prepared = prepare_run(scripted_config([]), "g", settings=settings)
    prepared.run.status = RunStatus.RUNNING
    await runs.save(prepared.run)
    assert await runs.mark_interrupted() == 1
    stored = await runs.get(prepared.run.id)
    assert stored.status == RunStatus.FAILED
    assert stored.error is not None and stored.error.type == "interrupted"


async def test_sql_memory_store(db: Database) -> None:
    store = SqlMemoryStore(db)
    record = await store.add(
        MemoryRecord(scope=MemoryScope.AGENT, namespace="agt", content="use make test", tags=["ci"])
    )
    await store.add(MemoryRecord(scope=MemoryScope.TASK, namespace="agt", content="other scope"))
    listed = await store.list_records(MemoryScope.AGENT, "agt")
    assert [r.id for r in listed] == [record.id] and listed[0].tags == ["ci"]
    hits = await store.search(MemoryScope.AGENT, "agt", "how to run make test")
    assert hits and hits[0].record.id == record.id
    assert await store.delete(record.id)


def _stored_run(
    created_at: datetime,
    status: RunStatus,
    *,
    cost: float | None = None,
    duration: float | None = None,
    tokens: tuple[int, int] = (0, 0),
    passed: bool | None = None,
) -> Run:
    return Run(
        agent_name="series-agent",
        config=scripted_config([{"text": "done"}]),
        goal="goal",
        status=status,
        created_at=created_at,
        usage=TokenUsage(input_tokens=tokens[0], output_tokens=tokens[1]),
        metrics=RunMetrics(cost_usd=cost, duration_seconds=duration),
        evaluation=(
            None if passed is None else EvaluationResult(passed=passed, score=float(passed))
        ),
    )


async def test_timeseries_buckets_runs_by_utc_day(db: Database) -> None:
    runs = RunRepository(db)
    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    for run in [
        # 8 March: one priced success and one failure without pricing.
        _stored_run(
            datetime(2026, 3, 8, 0, 0, tzinfo=UTC),
            RunStatus.SUCCEEDED,
            cost=0.25,
            duration=10.0,
            tokens=(100, 20),
            passed=True,
        ),
        _stored_run(
            datetime(2026, 3, 8, 23, 59, 59, tzinfo=UTC),
            RunStatus.FAILED,
            duration=20.0,
            tokens=(50, 5),
            passed=False,
        ),
        # 10 March: a timed-out run with unknown pricing and a still-running one,
        # whose tokens, cost and duration are not counted yet.
        _stored_run(datetime(2026, 3, 10, 1, 0, tzinfo=UTC), RunStatus.TIMED_OUT, tokens=(7, 3)),
        _stored_run(
            datetime(2026, 3, 10, 2, 0, tzinfo=UTC),
            RunStatus.RUNNING,
            cost=9.0,
            duration=99.0,
            tokens=(1000, 1000),
        ),
        # Outside the window on both sides.
        _stored_run(datetime(2026, 3, 7, 23, 59, 59, tzinfo=UTC), RunStatus.SUCCEEDED, cost=5.0),
        _stored_run(datetime(2026, 3, 11, 0, 0, tzinfo=UTC), RunStatus.SUCCEEDED, cost=5.0),
    ]:
        await runs.save(run)

    result = await runs.timeseries(days=3, now=now)
    assert result["days"] == 3 and result["timezone"] == "UTC"
    first, empty, last = result["series"]
    assert [d["date"] for d in result["series"]] == ["2026-03-08", "2026-03-09", "2026-03-10"]

    assert first == {
        "date": "2026-03-08",
        "runs": 2,
        "succeeded": 1,
        "failed": 1,
        "evaluated": 2,
        "passed": 1,
        "input_tokens": 150,
        "output_tokens": 25,
        "known_cost_usd": 0.25,
        "runs_with_unknown_cost": 1,
        "mean_duration_seconds": 15.0,
        "timed_runs": 2,
    }
    # A day without runs is present, with unknown (not zero) cost and duration.
    assert empty["runs"] == 0
    assert empty["known_cost_usd"] is None and empty["mean_duration_seconds"] is None
    # Unknown pricing is never reported as a zero cost.
    assert last["runs"] == 2 and last["failed"] == 1 and last["succeeded"] == 0
    assert last["known_cost_usd"] is None and last["runs_with_unknown_cost"] == 1
    assert (last["input_tokens"], last["output_tokens"]) == (7, 3)
    assert last["mean_duration_seconds"] is None and last["timed_runs"] == 0

    one_day = await runs.timeseries(days=1, now=now)
    assert [d["date"] for d in one_day["series"]] == ["2026-03-10"]
    with pytest.raises(ValueError, match="at least 1"):
        await runs.timeseries(days=0)


class _CountingEmbedder(Embedder):
    def __init__(self, name: str = "counting", dimensions: int = 64) -> None:
        self.name = name
        self.inner = HashingEmbedder(dimensions)
        self.texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return await self.inner.embed(texts)


async def _embedding_rows(db: Database) -> list[MemoryEmbeddingRow]:
    async with db.session() as session:
        return list((await session.scalars(select(MemoryEmbeddingRow))).all())


def _memory(content: str) -> MemoryRecord:
    return MemoryRecord(scope=MemoryScope.AGENT, namespace="agt", content=content)


async def test_sql_memory_vector_search_caches_embeddings(db: Database) -> None:
    # Written without an embedder: such records must be searchable later.
    plain = SqlMemoryStore(db)
    target = await plain.add(_memory("Database configuration lives in settings.py"))
    await plain.add(_memory("The weather service caches forecasts"))
    assert await _embedding_rows(db) == []
    assert await plain.search(MemoryScope.AGENT, "agt", "configuring databases") == []

    embedder = _CountingEmbedder(dimensions=256)
    store = SqlMemoryStore(db, embedder)
    hits = await store.search(
        MemoryScope.AGENT, "agt", "configuring databases", mode="vector", min_similarity=0.15
    )
    assert [hit.record.id for hit in hits] == [target.id]
    rows = await _embedding_rows(db)
    assert {row.memory_id for row in rows} == {
        r.id for r in await plain.list_records(MemoryScope.AGENT, "agt")
    }
    assert all(row.embedder == "counting" and row.dimensions == 256 for row in rows)
    assert all(len(row.vector) == 256 * 4 for row in rows)
    assert len(embedder.texts) == 3  # the query and the two records

    # A new store on the same database (a restarted server) reuses the vectors;
    # float32 storage keeps the ranking and, to 6 decimals, nearly the score.
    again = _CountingEmbedder(dimensions=256)
    hits_again = await SqlMemoryStore(db, again).search(
        MemoryScope.AGENT, "agt", "configuring databases", mode="vector", min_similarity=0.15
    )
    assert again.texts == ["configuring databases"]
    assert [hit.record.id for hit in hits_again] == [target.id]
    assert hits_again[0].score == pytest.approx(hits[0].score, abs=1e-5)

    hybrid = await store.search(MemoryScope.AGENT, "agt", "weather forecasts", mode="hybrid")
    assert hybrid[0].record.content == "The weather service caches forecasts"


async def test_sql_memory_embeddings_per_embedder_and_deleted_with_record(db: Database) -> None:
    store = SqlMemoryStore(db, _CountingEmbedder("first"))
    record = await store.add(_memory("alpha note"))
    other = await store.add(_memory("beta note"))
    await store.search(MemoryScope.AGENT, "agt", "alpha", mode="vector")
    store.embedder = _CountingEmbedder("second", dimensions=128)
    hits = await store.search(MemoryScope.AGENT, "agt", "alpha note", mode="vector")
    assert hits[0].record.id == record.id
    rows = await _embedding_rows(db)
    assert sorted((row.embedder, row.dimensions) for row in rows) == [
        ("first", 64),
        ("first", 64),
        ("second", 128),
        ("second", 128),
    ]

    assert await store.delete(record.id)
    assert {row.memory_id for row in await _embedding_rows(db)} == {other.id}
    assert not await store.delete(record.id)


async def test_sql_memory_unreadable_or_resized_vectors_are_replaced(db: Database) -> None:
    embedder = _CountingEmbedder()
    store = SqlMemoryStore(db, embedder)
    record = await store.add(_memory("alpha note"))
    await store.search(MemoryScope.AGENT, "agt", "alpha", mode="vector")
    async with db.transaction() as session:
        row = await session.get(MemoryEmbeddingRow, (record.id, "counting"))
        assert row is not None
        row.vector = b"\x01\x02\x03"  # not a float32 array
    embedder.texts.clear()
    hits = await store.search(MemoryScope.AGENT, "agt", "alpha note", mode="vector")
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert embedder.texts == ["alpha note", "alpha note"]  # the query, then the record again
    (row,) = await _embedding_rows(db)
    assert len(row.vector) == 64 * 4

    embedder.inner = HashingEmbedder(128)  # same name, another size
    await store.search(MemoryScope.AGENT, "agt", "alpha note", mode="vector")
    (row,) = await _embedding_rows(db)
    assert row.dimensions == 128 and len(row.vector) == 128 * 4


async def test_sql_memory_concurrent_vector_searches(db: Database) -> None:
    store = SqlMemoryStore(db, HashingEmbedder(64))
    for i in range(20):
        await store.add(_memory(f"deploy step {i}"))
    results = await asyncio.gather(
        *(
            store.search(MemoryScope.AGENT, "agt", "deploy step 3", mode="vector", limit=3)
            for _ in range(8)
        )
    )
    assert all(len(hits) == 3 for hits in results)
    assert len(await _embedding_rows(db)) == 20


async def test_sql_memory_vector_not_saved_for_a_record_deleted_meanwhile(db: Database) -> None:
    store = SqlMemoryStore(db, HashingEmbedder(64))
    record = await store.add(_memory("alpha note"))
    await store.delete(record.id)
    await store._save_vectors({record.id: [0.0] * 64}, "hashing-v1:64")
    assert await _embedding_rows(db) == []
