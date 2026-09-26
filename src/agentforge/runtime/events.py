"""Run lifecycle events and observers.

The runtime emits a :class:`RunEvent` at every significant point of a run.
Observers receive the event together with the current run record; they power
persistence, structured logs, live streaming to the dashboard and tracing.
Observer failures are logged and never abort a run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from agentforge.core.ids import utcnow
from agentforge.core.models import Run

logger = logging.getLogger("agentforge.runtime")


class RunEvent(BaseModel):
    run_id: str
    type: str
    timestamp: datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)


class RunObserver(Protocol):
    async def on_event(self, event: RunEvent, run: Run) -> None: ...


class LoggingObserver:
    async def on_event(self, event: RunEvent, run: Run) -> None:
        logger.info(event.type, extra={"run_id": run.id, "event": event.type, **event.data})


class EventBroadcaster:
    """In-process pub/sub used to stream run events (e.g. over SSE)."""

    def __init__(self, max_queue: int = 1_000) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent | None]]] = {}
        self._max_queue = max_queue

    def subscribe(self, run_id: str) -> asyncio.Queue[RunEvent | None]:
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(self._max_queue)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[RunEvent | None]) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(run_id, None)

    async def on_event(self, event: RunEvent, run: Run) -> None:
        for queue in list(self._subscribers.get(run.id, ())):
            if not queue.full():  # slow consumer: drop rather than block the run
                queue.put_nowait(event)
            if event.type == "run.finished":
                # The end-of-stream marker must always arrive, even for a slow
                # consumer: make room by discarding the oldest queued event.
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(None)


async def notify(observers: list[RunObserver], event: RunEvent, run: Run) -> None:
    for observer in observers:
        try:
            await observer.on_event(event, run)
        except Exception:
            logger.exception("run observer %s failed on %s", type(observer).__name__, event.type)
