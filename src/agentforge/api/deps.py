"""Shared API dependencies."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from agentforge.core.config import AgentConfig
from agentforge.service import AgentForgeService
from agentforge.storage import AgentRepository

audit_logger = logging.getLogger("agentforge.audit")


def audit(request: Request, action: str, **fields: object) -> None:
    """Structured audit record of a state-changing API action."""
    from agentforge.api.middleware import client_identity

    audit_logger.info(
        action,
        # Nested so field names can never collide with LogRecord attributes.
        extra={
            "audit": True,
            "action": action,
            "client": client_identity(request),
            "details": fields,
        },
    )


def get_service(request: Request) -> AgentForgeService:
    service: AgentForgeService = request.app.state.service
    return service


ServiceDep = Annotated[AgentForgeService, Depends(get_service)]


def require_api_key(request: Request) -> None:
    """Enforce ``Authorization: Bearer <AGENTFORGE_API_KEY>`` when a key is configured."""
    expected = get_service(request).settings.api_key
    if not expected:
        return
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def resolve_config(
    service: AgentForgeService, agent_id: str | None, config: AgentConfig | None
) -> tuple[AgentConfig, str | None]:
    if agent_id is not None:
        agent = await AgentRepository(service.db).get(agent_id)
        return agent.config, agent.id
    if config is None:  # pragma: no cover - guarded by request validation
        raise HTTPException(status_code=400, detail="agent_id or config required")
    return config, None
