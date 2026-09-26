"""Assemble a ready-to-execute runtime from an :class:`AgentConfig`."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agentforge.core.config import AgentConfig
from agentforge.core.models import Run
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.llm.base import LLMProvider
from agentforge.llm.pricing import PriceTable
from agentforge.llm.registry import create_provider
from agentforge.memory.base import MemoryStore
from agentforge.observability.redaction import Redactor
from agentforge.runtime.agent import AgentRuntime, RuntimeDeps
from agentforge.runtime.events import RunObserver
from agentforge.sandbox import create_sandbox
from agentforge.sandbox.workspace import Workspace
from agentforge.settings import Settings, get_settings
from agentforge.tools.base import ToolContext
from agentforge.tools.executor import ToolExecutor
from agentforge.tools.registry import ToolRegistry, default_registry


@dataclass
class PreparedRun:
    run: Run
    runtime: AgentRuntime
    provider: LLMProvider
    owns_provider: bool

    async def execute(self, evaluators: list[EvaluatorSpec] | None = None) -> Run:
        try:
            return await self.runtime.execute(self.run, evaluators)
        finally:
            if self.owns_provider:
                await self.provider.aclose()


def price_table_for(settings: Settings) -> PriceTable:
    if settings.pricing_file is not None:
        return PriceTable.from_file(settings.pricing_file)
    return PriceTable()


def prepare_run(
    config: AgentConfig,
    goal: str,
    *,
    agent_id: str | None = None,
    settings: Settings | None = None,
    registry: ToolRegistry | None = None,
    memory: MemoryStore | None = None,
    observers: list[RunObserver] | None = None,
    workspace_dir: str | Path | None = None,
    initial_files: dict[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    provider: LLMProvider | None = None,
    labels: dict[str, str] | None = None,
    parent_run_id: str | None = None,
    run: Run | None = None,
) -> PreparedRun:
    """Create the run record and wire all runtime dependencies.

    Pass ``run`` to execute an already-persisted pending run record.
    """
    settings = settings or get_settings()
    registry = registry or default_registry()
    environ = dict(os.environ if env is None else env)

    if run is None:
        run = Run(
            agent_id=agent_id,
            agent_name=config.name,
            config=config,
            goal=goal,
            labels={**config.labels, **(labels or {})},
            parent_run_id=parent_run_id,
        )
    workspace = Workspace(workspace_dir or settings.workspaces_dir / run.id).create()
    if initial_files:
        workspace.write_files(initial_files)
    run.workspace = str(workspace.root)

    sandbox = create_sandbox(config.sandbox, workspace, allow_local=settings.allow_local_sandbox)
    redactor = Redactor.from_environment(environ)
    tool_classes = registry.resolve(config.tools)
    ctx = ToolContext(
        run_id=run.id,
        workspace=workspace,
        sandbox=sandbox,
        redactor=redactor,
        settings=config.tool_settings,
        memory=memory if config.memory.enabled else None,
        agent_id=agent_id,
        env=environ,
    )
    executor = ToolExecutor(
        [cls() for cls in tool_classes],
        ctx,
        denied_permissions=set(settings.denied_permissions),
        max_output_chars=config.limits.max_output_chars,
    )
    owns_provider = provider is None
    llm = provider or create_provider(config.model, environ)
    runtime = AgentRuntime(
        config,
        RuntimeDeps(
            provider=llm,
            executor=executor,
            workspace=workspace,
            sandbox=sandbox,
            memory=memory,
            observers=list(observers or []),
            price_table=price_table_for(settings),
            redactor=redactor,
            env=environ,
        ),
    )
    return PreparedRun(run=run, runtime=runtime, provider=llm, owns_provider=owns_provider)


async def run_agent(
    config: AgentConfig,
    goal: str,
    *,
    evaluators: list[EvaluatorSpec] | None = None,
    **kwargs: object,
) -> Run:
    """Convenience wrapper: prepare and execute a run in one call."""
    prepared = prepare_run(config, goal, **kwargs)  # type: ignore[arg-type]
    return await prepared.execute(evaluators)
