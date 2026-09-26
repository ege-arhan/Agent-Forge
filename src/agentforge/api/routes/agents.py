"""Agent CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from agentforge.api.deps import ServiceDep, audit
from agentforge.api.schemas import AgentOut
from agentforge.core.config import AgentConfig
from agentforge.storage import AgentRepository

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
async def list_agents(service: ServiceDep) -> list[AgentOut]:
    return [AgentOut.of(a) for a in await AgentRepository(service.db).list()]


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(config: AgentConfig, service: ServiceDep, request: Request) -> AgentOut:
    service.policy.check_agent(config)
    agent = await AgentRepository(service.db).create(config)
    audit(request, "agent.create", agent_id=agent.id, name=agent.name)
    return AgentOut.of(agent)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, service: ServiceDep) -> AgentOut:
    return AgentOut.of(await AgentRepository(service.db).get(agent_id))


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str, config: AgentConfig, service: ServiceDep, request: Request
) -> AgentOut:
    service.policy.check_agent(config)
    agent = await AgentRepository(service.db).update(agent_id, config)
    audit(request, "agent.update", agent_id=agent.id, version=agent.version)
    return AgentOut.of(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, service: ServiceDep, request: Request) -> Response:
    await AgentRepository(service.db).delete(agent_id)
    audit(request, "agent.delete", agent_id=agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
