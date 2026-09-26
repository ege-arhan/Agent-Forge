"""Agent CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from agentforge.api.deps import ServiceDep
from agentforge.api.schemas import AgentOut
from agentforge.core.config import AgentConfig
from agentforge.storage import AgentRepository

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
async def list_agents(service: ServiceDep) -> list[AgentOut]:
    return [AgentOut.of(a) for a in await AgentRepository(service.db).list()]


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(config: AgentConfig, service: ServiceDep) -> AgentOut:
    return AgentOut.of(await AgentRepository(service.db).create(config))


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, service: ServiceDep) -> AgentOut:
    return AgentOut.of(await AgentRepository(service.db).get(agent_id))


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, config: AgentConfig, service: ServiceDep) -> AgentOut:
    return AgentOut.of(await AgentRepository(service.db).update(agent_id, config))


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, service: ServiceDep) -> Response:
    await AgentRepository(service.db).delete(agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
