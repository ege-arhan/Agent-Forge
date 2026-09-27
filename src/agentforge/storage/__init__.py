"""Persistence: database, repositories and the run persistence observer."""

from __future__ import annotations

from agentforge.core.models import Run
from agentforge.runtime.events import RunEvent
from agentforge.storage.db import Database
from agentforge.storage.repositories import (
    AgentRepository,
    RunPage,
    RunRepository,
    SqlMemoryStore,
)

__all__ = [
    "AgentRepository",
    "Database",
    "PersistenceObserver",
    "RunPage",
    "RunRepository",
    "SqlMemoryStore",
]

_PERSIST_ON = frozenset(
    {
        "run.started",
        "plan.created",
        "step.finished",
        "evaluation.finished",
        "run.finished",
        "tool.awaiting_approval",
        "tool.approved",
        "tool.denied",
    }
)


class PersistenceObserver:
    """Writes the run record at lifecycle checkpoints so progress is visible live."""

    def __init__(self, runs: RunRepository, *, benchmark_run_id: str | None = None) -> None:
        self._runs = runs
        self._benchmark_run_id = benchmark_run_id

    async def on_event(self, event: RunEvent, run: Run) -> None:
        if event.type in _PERSIST_ON:
            await self._runs.save(run, benchmark_run_id=self._benchmark_run_id)
