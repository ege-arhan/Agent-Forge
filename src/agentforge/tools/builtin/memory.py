"""Tools that let an agent write to and read from its persistent memory."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from agentforge.core.errors import ToolError
from agentforge.memory.base import MemoryRecord, MemoryScope
from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput


def _namespace(ctx: ToolContext) -> tuple[MemoryScope, str]:
    if ctx.agent_id:
        return MemoryScope.AGENT, ctx.agent_id
    return MemoryScope.RUN, ctx.run_id


class RememberInput(ToolInput):
    content: str = Field(min_length=1, max_length=5_000)
    tags: list[str] = Field(default_factory=list, max_length=10)


class Remember(Tool[RememberInput]):
    name = "remember"
    description = (
        "Save a durable note (fact, decision, lesson) to your long-term memory so future runs "
        "can recall it."
    )
    input_model = RememberInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.MEMORY})

    async def run(self, args: RememberInput, ctx: ToolContext) -> ToolOutput:
        if ctx.memory is None:
            raise ToolError("memory is not enabled for this agent")
        scope, namespace = _namespace(ctx)
        record = await ctx.memory.add(
            MemoryRecord(
                scope=scope,
                namespace=namespace,
                content=ctx.redactor.redact_text(args.content),
                tags=args.tags,
                metadata={"run_id": ctx.run_id, "source": "remember_tool"},
            )
        )
        return ToolOutput(content=f"saved memory {record.id}")


class RecallInput(ToolInput):
    query: str = Field(min_length=1, max_length=1_000)
    limit: int = Field(default=5, ge=1, le=20)


class Recall(Tool[RecallInput]):
    name = "recall"
    description = "Search your long-term memory for notes relevant to a query."
    input_model = RecallInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.MEMORY})

    async def run(self, args: RecallInput, ctx: ToolContext) -> ToolOutput:
        if ctx.memory is None:
            raise ToolError("memory is not enabled for this agent")
        scope, namespace = _namespace(ctx)
        hits = await ctx.memory.search(scope, namespace, args.query, limit=args.limit)
        if not hits:
            return ToolOutput(content="no relevant memories")
        return ToolOutput(content="\n".join(f"- ({h.score:.2f}) {h.record.content}" for h in hits))


MEMORY_TOOLS: list[type[Tool[Any]]] = [Remember, Recall]
