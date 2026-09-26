"""Schema migrations (Alembic), run programmatically at startup and by the CLI."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

from agentforge.core.errors import ConfigurationError
from agentforge.storage.db import Database

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _upgrade(connection: Connection, revision: str) -> None:
    tables = set(sa.inspect(connection).get_table_names())
    if "alembic_version" not in tables and "runs" in tables:
        raise ConfigurationError(
            "this database was created by a pre-migration development version of "
            "AgentForge; back it up and start with a fresh database"
        )
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


def _current(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def upgrade(db: Database, revision: str = "head") -> None:
    """Bring the database schema up to ``revision`` (default: latest)."""
    async with db.engine.begin() as conn:
        await conn.run_sync(_upgrade, revision)


async def current_revision(db: Database) -> str | None:
    async with db.engine.connect() as conn:
        return await conn.run_sync(_current)


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()
