"""Prometheus text-format metrics (no client library required)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from agentforge import __version__
from agentforge.api.deps import ServiceDep

router = APIRouter(tags=["meta"])


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def metric(self, name: str, kind: str, help_text: str) -> None:
        self.lines.append(f"# HELP {name} {help_text}")
        self.lines.append(f"# TYPE {name} {kind}")

    def sample(self, name: str, value: float, **labels: str) -> None:
        label_text = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()))
        suffix = f"{{{label_text}}}" if label_text else ""
        self.lines.append(f"{name}{suffix} {value:g}")

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(service: ServiceDep) -> str:
    stats = await service.runs.stats()
    durations = await service.runs.duration_summary()
    w = _Writer()

    w.metric("agentforge_info", "gauge", "AgentForge build information.")
    w.sample("agentforge_info", 1, version=__version__)

    w.metric("agentforge_runs", "gauge", "Stored runs by status.")
    for status, count in sorted(stats["runs_by_status"].items()):
        w.sample("agentforge_runs", count, status=status)

    w.metric("agentforge_active_runs", "gauge", "Runs currently pending or running.")
    w.sample("agentforge_active_runs", stats["active_runs"])

    w.metric("agentforge_evaluated_runs", "gauge", "Runs with an evaluation result.")
    w.sample("agentforge_evaluated_runs", stats["evaluated_runs"])
    w.metric("agentforge_evaluation_pass_ratio", "gauge", "Share of evaluated runs that passed.")
    if stats["evaluation_pass_rate"] is not None:
        w.sample("agentforge_evaluation_pass_ratio", stats["evaluation_pass_rate"])

    w.metric("agentforge_run_duration_seconds", "summary", "Duration of finished runs.")
    for status, agg in sorted(durations.items()):
        w.sample("agentforge_run_duration_seconds_sum", agg["sum"], status=status)
        w.sample("agentforge_run_duration_seconds_count", agg["count"], status=status)

    w.metric("agentforge_tool_calls", "gauge", "Recorded tool calls by tool and status.")
    for tool, by_status in sorted(stats["tool_calls"].items()):
        for status, count in sorted(by_status.items()):
            w.sample("agentforge_tool_calls", count, tool=tool, status=status)

    w.metric("agentforge_tokens", "gauge", "Provider-reported tokens across finished runs.")
    w.sample("agentforge_tokens", stats["input_tokens"], direction="input")
    w.sample("agentforge_tokens", stats["output_tokens"], direction="output")

    w.metric("agentforge_known_cost_usd", "gauge", "Estimated cost of runs with known pricing.")
    w.sample("agentforge_known_cost_usd", stats["known_cost_usd"])
    w.metric("agentforge_runs_unknown_cost", "gauge", "Finished runs whose cost is unknown.")
    w.sample("agentforge_runs_unknown_cost", stats["runs_with_unknown_cost"])
    return w.render()
