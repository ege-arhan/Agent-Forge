"""Built-in evaluators."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import Field

from agentforge.core.config import ModelConfig
from agentforge.core.models import RunStatus, ToolCallStatus
from agentforge.evaluation.base import (
    EvaluationContext,
    Evaluator,
    NoParams,
    Verdict,
    register_evaluator,
)


@register_evaluator
class CompletedEvaluator(Evaluator):
    type_name = "completed"
    description = "The agent finished with a final answer (no error, timeout or cancellation)."

    async def check(self, ctx: EvaluationContext) -> Verdict:
        run = ctx.run
        failed = run.status in (RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT)
        ok = run.result is not None and not failed
        return Verdict(passed=ok, details="" if ok else f"run status {run.status.value}")


class _TextParams(NoParams):
    text: str | list[str]
    case_sensitive: bool = False
    mode: Literal["all", "any"] = "all"


def _contains(haystack: str, needles: list[str], case_sensitive: bool) -> list[bool]:
    if not case_sensitive:
        haystack = haystack.lower()
        needles = [n.lower() for n in needles]
    return [n in haystack for n in needles]


@register_evaluator
class OutputContainsEvaluator(Evaluator):
    type_name = "output_contains"
    description = "The final answer contains the given text(s)."
    Params = _TextParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _TextParams = self.params
        needles = [params.text] if isinstance(params.text, str) else params.text
        hits = _contains(ctx.run.result or "", needles, params.case_sensitive)
        passed = all(hits) if params.mode == "all" else any(hits)
        missing = [n for n, hit in zip(needles, hits, strict=True) if not hit]
        return Verdict(
            passed=passed,
            score=sum(hits) / len(hits) if params.mode == "all" else float(passed),
            details="" if passed else f"missing: {missing}",
        )


class _RegexParams(NoParams):
    pattern: str
    flags: str = Field(default="", description="Any of 'i', 'm', 's'.")


def _compile(pattern: str, flags: str) -> re.Pattern[str]:
    value = 0
    for flag in flags:
        value |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}[flag]
    return re.compile(pattern, value)


@register_evaluator
class OutputMatchesEvaluator(Evaluator):
    type_name = "output_matches"
    description = "The final answer matches a regular expression."
    Params = _RegexParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _RegexParams = self.params
        ok = _compile(params.pattern, params.flags).search(ctx.run.result or "") is not None
        return Verdict(passed=ok, details="" if ok else f"no match for /{params.pattern}/")


class _PathParams(NoParams):
    path: str


@register_evaluator
class FileExistsEvaluator(Evaluator):
    type_name = "file_exists"
    description = "A file exists in the run workspace."
    Params = _PathParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _PathParams = self.params
        if ctx.workspace is None:
            return Verdict(passed=False, details="no workspace available")
        ok = ctx.workspace.resolve(params.path).is_file()
        return Verdict(passed=ok, details="" if ok else f"{params.path} does not exist")


class _FileContainsParams(NoParams):
    path: str
    text: str | None = None
    pattern: str | None = None
    flags: str = ""
    case_sensitive: bool = True


@register_evaluator
class FileContainsEvaluator(Evaluator):
    type_name = "file_contains"
    description = "A workspace file contains text or matches a regular expression."
    Params = _FileContainsParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _FileContainsParams = self.params
        if ctx.workspace is None:
            return Verdict(passed=False, details="no workspace available")
        path = ctx.workspace.resolve(params.path)
        if not path.is_file():
            return Verdict(passed=False, details=f"{params.path} does not exist")
        content = path.read_text(encoding="utf-8", errors="replace")
        if params.pattern is not None:
            ok = _compile(params.pattern, params.flags).search(content) is not None
            return Verdict(passed=ok, details="" if ok else f"/{params.pattern}/ not found")
        if params.text is None:
            return Verdict(passed=False, details="file_contains needs 'text' or 'pattern'")
        ok = _contains(content, [params.text], params.case_sensitive)[0]
        return Verdict(passed=ok, details="" if ok else f"'{params.text}' not found")


class _CommandParams(NoParams):
    command: str
    expect_exit_code: int = 0
    timeout_seconds: float = Field(default=300.0, gt=0, le=3_600)
    cwd: str = "."


@register_evaluator
class CommandEvaluator(Evaluator):
    """Runs a command (typically a test suite) in the run's sandbox."""

    type_name = "command"
    description = "A shell command (e.g. the test suite) exits with the expected code."
    Params = _CommandParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _CommandParams = self.params
        if ctx.sandbox is None:
            return Verdict(passed=False, details="no sandbox available")
        result = await ctx.sandbox.exec(
            ["sh", "-c", params.command], cwd=params.cwd, timeout=params.timeout_seconds
        )
        ok = result.exit_code == params.expect_exit_code and not result.timed_out
        tail = (result.stdout + "\n" + result.stderr).strip()[-1_500:]
        return Verdict(
            passed=ok,
            details=f"exit code {result.exit_code}" + ("" if ok else f"\n{tail}"),
            metrics={"exit_code": float(result.exit_code), "duration_ms": result.duration_ms},
        )


class _MaxStepsParams(NoParams):
    max_steps: int = Field(ge=1)


@register_evaluator
class MaxStepsEvaluator(Evaluator):
    type_name = "max_steps"
    description = "The run used at most N agent steps (efficiency check)."
    Params = _MaxStepsParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _MaxStepsParams = self.params
        steps = sum(1 for s in ctx.run.steps if s.kind.value == "action")
        ok = steps <= params.max_steps
        return Verdict(
            passed=ok,
            score=1.0 if ok else params.max_steps / steps,
            details=f"{steps} steps (limit {params.max_steps})",
            metrics={"steps": float(steps)},
        )


class _ToolUsedParams(NoParams):
    tool: str
    min_calls: int = Field(default=1, ge=0)
    successful_only: bool = True


@register_evaluator
class ToolUsedEvaluator(Evaluator):
    type_name = "tool_used"
    description = "A given tool was called (successfully) at least N times."
    Params = _ToolUsedParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        params: _ToolUsedParams = self.params
        calls = [
            c
            for c in ctx.run.tool_calls
            if c.tool == params.tool
            and (not params.successful_only or c.status == ToolCallStatus.SUCCESS)
        ]
        ok = len(calls) >= params.min_calls
        return Verdict(passed=ok, details=f"{params.tool} called {len(calls)} time(s)")


class _JudgeParams(NoParams):
    rubric: str
    model: dict[str, Any] = Field(description="ModelConfig for the judge model.")
    pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    include_tool_calls: bool = True


JUDGE_PROMPT = """You are grading the work of an AI agent against a rubric.

Rubric:
{rubric}

Agent goal:
{goal}

Agent final answer:
{result}
{trace}
Respond with a single JSON object and nothing else:
{{"score": <number between 0 and 1>, "reason": "<one or two sentences>"}}"""


@register_evaluator
class LLMJudgeEvaluator(Evaluator):
    """Asks a (separately configured) model to grade the run against a rubric.

    LLM judgments are noisy and can be biased; prefer deterministic checks
    where possible and treat judge scores as a secondary signal.
    """

    type_name = "llm_judge"
    description = "A judge model scores the result against a rubric (0-1)."
    Params = _JudgeParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        from agentforge.llm.registry import create_provider
        from agentforge.llm.types import CompletionRequest, Message

        params: _JudgeParams = self.params
        model = ModelConfig.model_validate(params.model)
        trace = ""
        if params.include_tool_calls and ctx.run.tool_calls:
            lines = [
                f"- {c.tool}({json.dumps(c.arguments)[:200]}) -> {c.status.value}"
                for c in ctx.run.tool_calls[:50]
            ]
            trace = "\nTool calls made:\n" + "\n".join(lines) + "\n"
        prompt = JUDGE_PROMPT.format(
            rubric=params.rubric, goal=ctx.run.goal, result=ctx.run.result or "(none)", trace=trace
        )
        provider = create_provider(model, ctx.env or None)
        try:
            response = await provider.complete(
                CompletionRequest(
                    model=model.model,
                    messages=[Message.user(prompt)],
                    max_tokens=model.max_tokens,
                    temperature=model.temperature,
                )
            )
        finally:
            await provider.aclose()
        text = response.message.text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return Verdict(passed=False, score=0.0, details=f"judge returned no JSON: {text[:200]}")
        try:
            data = json.loads(match.group(0))
            score = float(data["score"])
        except (ValueError, KeyError, TypeError):
            return Verdict(
                passed=False, score=0.0, details=f"unparseable judge output: {text[:200]}"
            )
        score = min(1.0, max(0.0, score))
        return Verdict(
            passed=score >= params.pass_threshold,
            score=score,
            details=str(data.get("reason", ""))[:500],
        )
