from __future__ import annotations

import pytest

from agentforge.core.errors import NotFoundError
from agentforge.core.models import RunStatus
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.memory.base import MemoryRecord, MemoryScope
from agentforge.runtime.factory import prepare_run
from agentforge.settings import Settings
from agentforge.storage import (
    AgentRepository,
    Database,
    PersistenceObserver,
    RunRepository,
    SqlMemoryStore,
)
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
