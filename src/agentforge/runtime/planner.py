"""Planning strategies.

* ``react`` - no upfront plan; the model decides the next action every step
  (reason + act, interleaved with observations).
* ``plan_execute`` - the model first writes an explicit numbered plan without
  tools; the plan is recorded on the run and included in the system prompt of
  the execution loop, which the model can revise as it learns more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentforge.core.config import PlannerConfig, PlannerStrategy
from agentforge.llm.types import CompletionResponse, Message

PLAN_PROMPT = """Before acting, write a short plan for the goal below.

Goal:
{goal}

Available tools: {tools}

Reply with a numbered list of at most {max_steps} concrete steps (one per line, "1. ..."),
and nothing else."""

_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)\s*$")


@dataclass
class PlanRequest:
    prompt: Message


def build_plan_request(
    config: PlannerConfig, goal: str, tool_names: list[str]
) -> PlanRequest | None:
    if config.strategy == PlannerStrategy.REACT:
        return None
    prompt = PLAN_PROMPT.format(
        goal=goal, tools=", ".join(tool_names) or "(none)", max_steps=config.max_plan_steps
    )
    return PlanRequest(prompt=Message.user(prompt))


def parse_plan(response: CompletionResponse, max_steps: int) -> list[str]:
    items: list[str] = []
    for line in response.message.text.splitlines():
        match = _ITEM.match(line)
        if match:
            items.append(match.group(1))
    if not items:
        text = response.message.text.strip()
        items = [text] if text else []
    return items[:max_steps]


def plan_section(plan: list[str]) -> str:
    steps = "\n".join(f"{i}. {item}" for i, item in enumerate(plan, start=1))
    return (
        "# Plan\nYou wrote this plan before starting. Follow it, but adapt if you learn "
        f"something that changes it:\n{steps}"
    )
