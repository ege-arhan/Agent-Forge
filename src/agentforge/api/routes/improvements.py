"""Agent improvement loop: analysis → proposal → new version → re-benchmark → comparison."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from agentforge.api.deps import ServiceDep, audit
from agentforge.api.schemas import ImprovementApply, ImprovementCreate, ImprovementReject
from agentforge.improvement import CATEGORY_DESCRIPTIONS, ImprovementCycle

router = APIRouter(prefix="/improvements", tags=["improvements"])


@router.get("/categories")
async def failure_categories() -> dict[str, str]:
    """Failure categories used by the analysis, with descriptions."""
    return {category.value: text for category, text in CATEGORY_DESCRIPTIONS.items()}


@router.post("", response_model=ImprovementCycle, status_code=status.HTTP_201_CREATED)
async def create_improvement(
    body: ImprovementCreate, service: ServiceDep, request: Request
) -> ImprovementCycle:
    """Analyse a finished benchmark of a stored agent version and record a proposal."""
    cycle = await service.improvements.propose(
        body.benchmark_run_id, changes=body.changes, notes=body.notes
    )
    audit(
        request,
        "improvement.propose",
        improvement_id=cycle.id,
        agent_id=cycle.agent_id,
        benchmark_run_id=body.benchmark_run_id,
    )
    return cycle


@router.get("", response_model=list[ImprovementCycle])
async def list_improvements(
    service: ServiceDep,
    agent_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ImprovementCycle]:
    return await service.improvements.cycles.list(agent_id=agent_id, limit=limit)


@router.get("/{cycle_id}", response_model=ImprovementCycle)
async def get_improvement(cycle_id: str, service: ServiceDep) -> ImprovementCycle:
    return await service.improvements.cycles.get(cycle_id)


@router.post("/{cycle_id}/apply", response_model=ImprovementCycle)
async def apply_improvement(
    cycle_id: str, service: ServiceDep, request: Request, body: ImprovementApply | None = None
) -> ImprovementCycle:
    """Create the next agent version from (a subset of) the proposal."""
    cycle = await service.improvements.apply(cycle_id, body.change_ids if body else None)
    audit(request, "improvement.apply", improvement_id=cycle.id, version=cycle.to_version)
    return cycle


@router.post(
    "/{cycle_id}/evaluate", response_model=ImprovementCycle, status_code=status.HTTP_202_ACCEPTED
)
async def evaluate_improvement(
    cycle_id: str, service: ServiceDep, request: Request
) -> ImprovementCycle:
    """Benchmark the new version on the baseline's suite snapshot, then compare."""
    cycle = await service.start_improvement_evaluation(cycle_id)
    audit(
        request,
        "improvement.evaluate",
        improvement_id=cycle.id,
        benchmark_run_id=cycle.candidate_benchmark_run_id,
    )
    return cycle


@router.post("/{cycle_id}/reject", response_model=ImprovementCycle)
async def reject_improvement(
    cycle_id: str, service: ServiceDep, request: Request, body: ImprovementReject | None = None
) -> ImprovementCycle:
    """Decline a proposal; an applied version is reverted by storing the baseline again."""
    cycle = await service.improvements.reject(cycle_id, body.reason if body else "")
    audit(
        request,
        "improvement.reject",
        improvement_id=cycle.id,
        reverted_to_version=cycle.reverted_to_version,
    )
    return cycle
