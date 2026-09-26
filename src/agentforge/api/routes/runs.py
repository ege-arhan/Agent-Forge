"""Run endpoints: create, list, inspect, cancel, re-run and stream events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from agentforge.api.deps import ServiceDep, audit, resolve_config
from agentforge.api.schemas import RunCreate, RunList, RunSummary
from agentforge.core.models import Run, RunStatus
from agentforge.evaluation.base import EvaluatorSpec

router = APIRouter(prefix="/runs", tags=["runs"])

HEARTBEAT_SECONDS = 15.0


@router.post("", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def create_run(body: RunCreate, service: ServiceDep, request: Request) -> Run:
    config, agent_id = await resolve_config(service, body.agent_id, body.config)
    run = await service.start_run(
        config, body.goal, agent_id=agent_id, evaluators=body.evaluators, labels=body.labels
    )
    audit(request, "run.create", run_id=run.id, agent=run.agent_name)
    return run


@router.get("", response_model=RunList)
async def list_runs(  # noqa: PLR0917 - FastAPI query parameters
    service: ServiceDep,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
    agent_id: str | None = None,
    benchmark_run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    page = await service.runs.list(
        status=status_filter,
        agent_id=agent_id,
        benchmark_run_id=benchmark_run_id,
        limit=limit,
        offset=offset,
    )
    return RunList(items=[RunSummary.of(r) for r in page.items], total=page.total)


@router.get("/{run_id}", response_model=Run)
async def get_run(run_id: str, service: ServiceDep) -> Run:
    return await service.runs.get(run_id)


@router.post("/{run_id}/cancel", response_model=Run)
async def cancel_run(run_id: str, service: ServiceDep, request: Request) -> Run:
    audit(request, "run.cancel", run_id=run_id)
    return await service.cancel_run(run_id)


@router.post("/{run_id}/rerun", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def rerun(run_id: str, service: ServiceDep, request: Request) -> Run:
    """Reproduce a run: same goal and the exact agent config snapshot it used."""
    original = await service.runs.get(run_id)
    evaluators = [EvaluatorSpec.model_validate(spec) for spec in original.evaluators]
    run = await service.start_run(
        original.config,
        original.goal,
        agent_id=original.agent_id,
        evaluators=evaluators,
        labels={**original.labels, "rerun_of": original.id},
        parent_run_id=original.id,
    )
    audit(request, "run.rerun", run_id=run.id, parent_run_id=original.id)
    return run


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request, service: ServiceDep) -> StreamingResponse:
    """Server-sent events for a run. Ends when the run finishes."""
    run = await service.runs.get(run_id)
    queue = service.broadcaster.subscribe(run_id)

    async def events() -> AsyncIterator[str]:
        try:
            yield _sse("snapshot", {"status": run.status.value, "steps": len(run.steps)})
            if run.status.is_terminal and not service.is_active(run_id):
                return
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    if not service.is_active(run_id):
                        return  # finished while we waited: never leave a client hanging
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    return
                yield _sse(event.type, event.model_dump(mode="json"))
        finally:
            service.broadcaster.unsubscribe(run_id, queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
