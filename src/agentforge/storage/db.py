"""Database engine, session management and ORM tables.

SQLite (via aiosqlite) is the zero-configuration default; PostgreSQL (via
asyncpg) is used in the Docker Compose deployment. Structured sub-documents
(configs, steps, evaluations) are stored as JSON columns; fields that are
filtered or aggregated on are real columns.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Dialect,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONType, list[Any]: JSONType}


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend.

    SQLite has no timezone support and returns naive values; this type stores
    UTC and always returns aware UTC datetimes so records round-trip exactly.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use timezone-aware UTC")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _tz() -> UTCDateTime:
    return UTCDateTime()


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(_tz())
    updated_at: Mapped[datetime] = mapped_column(_tz())


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(_tz(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(_tz())
    finished_at: Mapped[datetime | None] = mapped_column(_tz())
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONType)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    steps: Mapped[list[Any]] = mapped_column(JSONType)
    plan: Mapped[list[Any] | None] = mapped_column(JSONType)
    workspace: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONType)
    parent_run_id: Mapped[str | None] = mapped_column(String(64))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    benchmark_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    evaluators: Mapped[list[Any]] = mapped_column(JSONType, default=list)


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_tool_status", "tool", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    step_index: Mapped[int] = mapped_column(Integer)
    call_id: Mapped[str] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(_tz())


class MemoryRow(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_scope_ns", "scope", "namespace"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    namespace: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[Any]] = mapped_column(JSONType)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType)
    created_at: Mapped[datetime] = mapped_column(_tz(), index=True)


class BenchmarkRunRow(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suite_id: Mapped[str] = mapped_column(String(128), index=True)
    suite_name: Mapped[str] = mapped_column(String(200))
    agent_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(_tz(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(_tz())
    repeats: Mapped[int] = mapped_column(Integer)
    agent_config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    suite: Mapped[dict[str, Any]] = mapped_column(JSONType)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    results: Mapped[list[Any]] = mapped_column(JSONType)
    experiment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    variant: Mapped[str | None] = mapped_column(String(128))
    environment: Mapped[dict[str, Any]] = mapped_column(JSONType)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(_tz(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(_tz())
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONType)


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        kwargs: dict[str, Any] = {"echo": echo}
        if self.is_sqlite:
            kwargs["connect_args"] = {"timeout": 30}
            path = url.split("///", 1)[-1]
            if path and path != ":memory:" and not path.startswith(":"):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        else:
            kwargs["pool_pre_ping"] = True
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        if self.is_sqlite:
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        # SQLite allows one writer at a time; serialise writes in-process.
        self._write_lock = asyncio.Lock() if self.is_sqlite else None

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        if self._write_lock is None:
            async with self._sessions() as session, session.begin():
                yield session
            return
        async with self._write_lock, self._sessions() as session, session.begin():
            yield session


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
