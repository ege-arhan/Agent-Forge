"""Human approval gate: pause a tool call until an operator decides.

One :class:`ApprovalGate` belongs to one :class:`~agentforge.runtime.agent.AgentRuntime`
(one run). When the runtime finds a tool call that needs approval, it calls
:meth:`ApprovalGate.request` and awaits the result; the API/CLI layer resolves
it with :meth:`ApprovalGate.decide`, from another coroutine (an HTTP handler)
or, for the interactive CLI, a terminal prompt observing the same run.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agentforge.core.ids import utcnow


@dataclass
class PendingApproval:
    """A tool call currently waiting for a decision."""

    call_id: str
    tool: str
    arguments: dict[str, Any]
    permissions: frozenset[str]
    requested_at: datetime = field(default_factory=utcnow)


class ApprovalGate:
    """Tracks tool calls awaiting a human decision for one run."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._futures: dict[str, asyncio.Future[tuple[bool, str | None]]] = {}

    @property
    def pending(self) -> list[PendingApproval]:
        return list(self._pending.values())

    def begin(
        self, call_id: str, tool: str, arguments: dict[str, Any], permissions: frozenset[str]
    ) -> None:
        """Register the pending call so :meth:`decide` can resolve it right away.

        Synchronous and separate from :meth:`wait` so a caller can register the
        request, tell observers about it (who may decide synchronously, e.g. a
        non-interactive CLI), and only then start waiting -- without a window
        where a decision arrives before anything is listening for it.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[bool, str | None]] = loop.create_future()
        self._pending[call_id] = PendingApproval(
            call_id=call_id, tool=tool, arguments=arguments, permissions=permissions
        )
        self._futures[call_id] = future

    async def wait(
        self, call_id: str, *, timeout: float, cancel_event: asyncio.Event
    ) -> tuple[bool, str | None]:
        """Block until :meth:`decide` is called, the cancel event fires, or ``timeout``."""
        future = self._futures[call_id]
        cancel_wait = asyncio.ensure_future(cancel_event.wait())
        waitables: set[asyncio.Future[Any]] = {future, cancel_wait}
        try:
            done, _ = await asyncio.wait(
                waitables, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if future in done:
                return future.result()
            if cancel_wait in done:
                return False, "run was cancelled while awaiting approval"
            return False, f"no approval decision within {timeout:g}s"
        finally:
            cancel_wait.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_wait
            self._pending.pop(call_id, None)
            self._futures.pop(call_id, None)

    async def request(
        self,
        call_id: str,
        tool: str,
        arguments: dict[str, Any],
        permissions: frozenset[str],
        *,
        timeout: float,
        cancel_event: asyncio.Event,
    ) -> tuple[bool, str | None]:
        """Convenience: :meth:`begin` immediately followed by :meth:`wait`."""
        self.begin(call_id, tool, arguments, permissions)
        return await self.wait(call_id, timeout=timeout, cancel_event=cancel_event)

    def decide(self, call_id: str, approved: bool, reason: str | None = None) -> bool:
        """Resolve a pending request. Returns ``False`` if nothing is pending for ``call_id``."""
        future = self._futures.get(call_id)
        if future is None or future.done():
            return False
        future.set_result((approved, reason))
        return True
