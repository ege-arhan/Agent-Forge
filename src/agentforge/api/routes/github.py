"""GitHub endpoints: repository inspection, issues and issue tasks."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentforge.api.deps import ServiceDep, resolve_config
from agentforge.api.schemas import RunList, RunSummary
from agentforge.core.config import AgentConfig
from agentforge.core.models import Run
from agentforge.integrations.github.client import Issue

router = APIRouter(prefix="/github", tags=["github"])


class GitHubTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    issue_number: int = Field(ge=1)
    agent_id: str | None = None
    config: AgentConfig | None = None
    base_branch: str | None = None
    test_command: str | None = Field(default=None, max_length=2_000)
    push: bool = False
    open_pr: bool = False
    allow_failing: bool = False

    @model_validator(mode="after")
    def _check(self) -> GitHubTaskCreate:
        if (self.agent_id is None) == (self.config is None):
            raise ValueError("provide exactly one of agent_id or config")
        if self.open_pr and not self.push:
            raise ValueError("open_pr requires push")
        return self


@router.get("/status")
async def github_status(service: ServiceDep) -> dict[str, Any]:
    return {
        "token_configured": bool(service.github_token()),
        "token_env": service.settings.github_token_env,
    }


@router.get("/repos/{owner}/{repo}")
async def get_repository(owner: str, repo: str, service: ServiceDep) -> dict[str, Any]:
    async with service.github_client() as client:
        data: dict[str, Any] = await client.get_repository(f"{owner}/{repo}")
        return data


@router.get("/repos/{owner}/{repo}/issues", response_model=list[Issue])
async def list_issues(  # noqa: PLR0917 - FastAPI parameters
    owner: str,
    repo: str,
    service: ServiceDep,
    state: Annotated[str, Query(pattern="^(open|closed|all)$")] = "open",
    labels: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[Issue]:
    async with service.github_client() as client:
        issues: list[Issue] = await client.list_issues(
            f"{owner}/{repo}", state=state, labels=labels, limit=limit
        )
        return issues


@router.post("/tasks", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def create_task(body: GitHubTaskCreate, service: ServiceDep) -> Run:
    config, agent_id = await resolve_config(service, body.agent_id, body.config)
    return await service.start_github_task(
        repo=body.repo,
        issue_number=body.issue_number,
        config=config,
        agent_id=agent_id,
        base_branch=body.base_branch,
        test_command=body.test_command,
        push=body.push,
        open_pr=body.open_pr,
        allow_failing=body.allow_failing,
    )


@router.get("/tasks", response_model=RunList)
async def list_tasks(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    page = await service.runs.list(label="github_repo", limit=limit, offset=offset)
    return RunList(items=[RunSummary.of(r) for r in page.items], total=page.total)
