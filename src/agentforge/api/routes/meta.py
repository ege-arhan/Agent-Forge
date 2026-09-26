"""Health, capabilities and statistics endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from agentforge import __version__
from agentforge.api.deps import ServiceDep
from agentforge.api.schemas import Health
from agentforge.core.ids import utcnow
from agentforge.evaluation import available_evaluators
from agentforge.llm.registry import available_providers
from agentforge.tools.registry import default_registry

public = APIRouter(tags=["meta"])
router = APIRouter(tags=["meta"])


@public.get("/health", response_model=Health)
async def health(service: ServiceDep) -> Health:
    try:
        async with service.db.session() as session:
            await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return Health(
        status="ok" if database == "ok" else "degraded", version=__version__, database=database
    )


@router.get("/providers")
async def providers() -> list[dict[str, Any]]:
    return [asdict(p) for p in available_providers()]


@router.get("/tools")
async def tools() -> dict[str, Any]:
    registry = default_registry()
    return {"tools": [asdict(t) for t in registry.describe()], "toolsets": registry.toolsets()}


@router.get("/evaluators")
async def evaluators() -> list[dict[str, Any]]:
    return [
        {
            "type": name,
            "description": cls.description,
            "params_schema": cls.Params.model_json_schema(),
        }
        for name, cls in available_evaluators().items()
    ]


@router.get("/stats")
async def stats(
    service: ServiceDep,
    days: Annotated[int | None, Query(ge=1, le=3650)] = None,
) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days) if days else None
    return await service.runs.stats(since=since)
