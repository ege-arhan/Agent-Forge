from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.memory.base import InMemoryMemoryStore
from agentforge.observability.redaction import Redactor
from agentforge.sandbox.local import LocalSandbox
from agentforge.sandbox.workspace import Workspace
from agentforge.settings import Settings
from agentforge.storage.db import Base, Database
from agentforge.tools.base import ToolContext


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "ws").create()


@pytest.fixture
def tool_ctx(workspace: Workspace) -> ToolContext:
    return ToolContext(
        run_id="run_test",
        workspace=workspace,
        sandbox=LocalSandbox(workspace),
        redactor=Redactor(["super-secret-value"]),
        memory=InMemoryMemoryStore(),
        agent_id="agt_test",
    )


# Set to a PostgreSQL URL (postgresql+asyncpg://...) to run storage, API and
# CLI tests against PostgreSQL instead of per-test SQLite files. Tables are
# dropped and recreated for every test.
TEST_DATABASE_URL = os.environ.get("AGENTFORGE_TEST_DATABASE_URL")


@pytest.fixture
async def settings(tmp_path: Path) -> Settings:
    url = TEST_DATABASE_URL or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    if TEST_DATABASE_URL:
        await reset_database(url)
    return Settings(
        data_dir=tmp_path / "data",
        database_url=url,
        benchmarks_dir=Path(__file__).resolve().parents[1] / "examples" / "benchmarks",
        _env_file=None,  # type: ignore[call-arg]
    )


async def reset_database(url: str) -> None:
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await database.dispose()


@pytest.fixture
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings.resolved_database_url)
    await database.create_all()
    yield database
    await database.dispose()


def scripted_config(
    turns: list[dict[str, Any]],
    *,
    tools: list[str] | None = None,
    name: str = "test-agent",
    **overrides: Any,
) -> AgentConfig:
    data: dict[str, Any] = {
        "name": name,
        "model": ModelConfig(provider="scripted", options={"turns": turns}),
        "tools": tools if tools is not None else ["filesystem"],
    }
    data.update(overrides)
    return AgentConfig.model_validate(data)
