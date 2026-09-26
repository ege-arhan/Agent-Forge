from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy.engine import Connection

from agentforge.core.errors import ConfigurationError
from agentforge.settings import Settings
from agentforge.storage.db import Base, Database
from agentforge.storage.migrate import alembic_config, current_revision, head_revision, upgrade

pytestmark = pytest.mark.integration


def _check(connection: Connection) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    # Raises if the ORM models differ from the schema produced by migrations.
    command.check(config)


async def test_migrations_create_schema_matching_models(settings: Settings) -> None:
    db = Database(settings.resolved_database_url)
    try:
        await upgrade(db)
        assert await current_revision(db) == head_revision()
        await upgrade(db)  # idempotent
        async with db.engine.connect() as conn:
            await conn.run_sync(_check)
    finally:
        await db.dispose()


async def test_pre_migration_database_is_rejected(settings: Settings) -> None:
    db = Database(settings.resolved_database_url)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        with pytest.raises(ConfigurationError, match="pre-migration"):
            await upgrade(db)
    finally:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await db.dispose()
