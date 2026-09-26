"""Alembic environment.

Migrations are run programmatically by ``agentforge.storage.migrate``, which
passes an open (sync-adapted) connection in ``config.attributes``. Running the
``alembic`` CLI directly is supported for development via
``alembic -c src/agentforge/storage/migrations/alembic.ini``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from alembic import context
from sqlalchemy.engine import Connection

from agentforge.storage.db import Base

target_metadata = Base.metadata


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite lacks ALTER support
        compare_type=True,
        user_module_prefix="agentforge.storage.db.",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection: Any = context.config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return

    # Standalone CLI usage: build an engine from the configured URL.
    from agentforge.storage.db import Database

    url = context.config.get_main_option("sqlalchemy.url")
    if not url:
        from agentforge.settings import get_settings

        url = get_settings().resolved_database_url

    async def _run() -> None:
        db = Database(url)
        async with db.engine.connect() as conn:
            await conn.run_sync(_configure_and_run)
            await conn.commit()
        await db.dispose()

    asyncio.run(_run())


if context.is_offline_mode():  # pragma: no cover - offline SQL generation
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
