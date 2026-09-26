"""Safe tool invocation: validation, permissions, timeouts, redaction, records."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic import ValidationError

from agentforge.core.errors import AgentForgeError, PermissionDeniedError, ToolError
from agentforge.core.ids import utcnow
from agentforge.core.models import ToolCallRecord, ToolCallStatus
from agentforge.llm.types import ToolResultPart, ToolSpec, ToolUsePart
from agentforge.tools.base import Permission, Tool, ToolContext, ToolOutput

logger = logging.getLogger("agentforge.tools")


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = int(limit * 0.7)
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n... [{omitted} characters truncated] ...\n{text[-tail:]}", True


def _format_validation_error(exc: ValidationError) -> str:
    problems = []
    for err in exc.errors()[:10]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        problems.append(f"{loc}: {err['msg']}")
    return "invalid tool input: " + "; ".join(problems)


class ToolExecutor:
    """Executes the tool calls requested by a model on behalf of one run."""

    def __init__(
        self,
        tools: list[Tool[Any]],
        ctx: ToolContext,
        *,
        denied_permissions: set[Permission] | None = None,
        max_output_chars: int = 20_000,
    ) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._ctx = ctx
        self._denied = denied_permissions or set()
        self._max_output = max_output_chars

    @property
    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    async def execute(self, call: ToolUsePart) -> tuple[ToolCallRecord, ToolResultPart]:
        started_at = utcnow()
        t0 = time.monotonic()
        redactor = self._ctx.redactor
        safe_args = redactor.redact(call.arguments)
        status = ToolCallStatus.SUCCESS
        error: str | None = None
        output = ToolOutput(content="")

        tool = self._tools.get(call.name)
        try:
            if tool is None:
                status = ToolCallStatus.INVALID_INPUT
                available = ", ".join(sorted(self._tools)) or "(none)"
                output = ToolOutput.error(f"unknown tool '{call.name}'. Available: {available}")
            elif "__invalid_json__" in call.arguments:
                status = ToolCallStatus.INVALID_INPUT
                output = ToolOutput.error("tool arguments were not valid JSON; send a JSON object")
            else:
                denied = tool.permissions & self._denied
                if denied:
                    raise PermissionDeniedError(
                        f"tool '{tool.name}' requires permissions denied by policy: "
                        + ", ".join(sorted(p.value for p in denied))
                    )
                args = tool.input_model.model_validate(call.arguments)
                timeout = float(
                    self._ctx.settings.get(tool.name, {}).get("timeout_seconds")
                    or tool.timeout_seconds
                )
                output = await asyncio.wait_for(tool.run(args, self._ctx), timeout=timeout)
                if output.is_error:
                    status = ToolCallStatus.ERROR
        except ValidationError as exc:
            status = ToolCallStatus.INVALID_INPUT
            output = ToolOutput.error(_format_validation_error(exc))
        except PermissionDeniedError as exc:
            status = ToolCallStatus.DENIED
            output = ToolOutput.error(exc.message)
        except TimeoutError:
            status = ToolCallStatus.TIMEOUT
            output = ToolOutput.error(f"tool '{call.name}' timed out")
        except (ToolError, AgentForgeError) as exc:
            status = ToolCallStatus.ERROR
            output = ToolOutput.error(exc.message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Unexpected failures are reported to the model rather than
            # crashing the run; the full traceback goes to the log only.
            logger.exception("tool %s raised unexpectedly", call.name)
            status = ToolCallStatus.ERROR
            output = ToolOutput.error(f"internal error in tool '{call.name}': {type(exc).__name__}")

        content = redactor.redact_text(output.content)
        content, truncated = truncate(content, self._max_output)
        if status != ToolCallStatus.SUCCESS:
            error = content
        finished_at = utcnow()
        record = ToolCallRecord(
            id=call.id,
            tool=call.name,
            arguments=safe_args,
            status=status,
            output=content,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((time.monotonic() - t0) * 1000),
            truncated=truncated,
        )
        logger.info(
            "tool call finished",
            extra={
                "run_id": self._ctx.run_id,
                "tool": call.name,
                "status": status.value,
                "duration_ms": record.duration_ms,
            },
        )
        result = ToolResultPart(
            tool_use_id=call.id,
            content=content or "(no output)",
            is_error=status != ToolCallStatus.SUCCESS,
        )
        return record, result
