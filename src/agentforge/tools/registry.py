"""Plugin-style tool registry.

Tools are registered by class. Toolsets group related tools under one name
(``filesystem``, ``terminal``, ...) so agent configs can enable them together.
Third-party packages can contribute tools through the ``agentforge.tools``
entry-point group; each entry point must resolve to a ``Tool`` subclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from agentforge.core.errors import ConfigurationError
from agentforge.tools.base import Permission, Tool

ToolClass = type[Tool[Any]]


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    toolset: str | None
    permissions: list[str]
    timeout_seconds: float
    input_schema: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolClass] = {}
        self._toolsets: dict[str, list[str]] = {}
        self._toolset_of: dict[str, str] = {}

    def register(self, tool: ToolClass, *, toolset: str | None = None) -> ToolClass:
        name = tool.name
        if name in self._tools and self._tools[name] is not tool:
            raise ConfigurationError(f"tool '{name}' is already registered")
        if name in self._toolsets:
            raise ConfigurationError(f"tool name '{name}' clashes with a toolset")
        self._tools[name] = tool
        if toolset:
            if toolset in self._tools:
                raise ConfigurationError(f"toolset name '{toolset}' clashes with a tool")
            members = self._toolsets.setdefault(toolset, [])
            if name not in members:
                members.append(name)
            self._toolset_of[name] = toolset
        return tool

    def get(self, name: str) -> ToolClass:
        try:
            return self._tools[name]
        except KeyError:
            raise ConfigurationError(f"unknown tool '{name}'") from None

    def resolve(self, names: list[str]) -> list[ToolClass]:
        """Expand tool and toolset names into unique tool classes (order kept)."""
        seen: dict[str, ToolClass] = {}
        for name in names:
            if name in self._toolsets:
                for member in self._toolsets[name]:
                    seen.setdefault(member, self._tools[member])
            else:
                seen.setdefault(name, self.get(name))
        return list(seen.values())

    def toolsets(self) -> dict[str, list[str]]:
        return {name: list(members) for name, members in self._toolsets.items()}

    def describe(self) -> list[ToolInfo]:
        return [
            ToolInfo(
                name=tool.name,
                description=tool.description,
                toolset=self._toolset_of.get(tool.name),
                permissions=sorted(p.value for p in tool.permissions),
                timeout_seconds=tool.timeout_seconds,
                input_schema=tool.spec().input_schema,
            )
            for tool in sorted(self._tools.values(), key=lambda t: t.name)
        ]

    def load_entry_points(self) -> None:
        for ep in entry_points(group="agentforge.tools"):
            tool = ep.load()
            if not (isinstance(tool, type) and issubclass(tool, Tool)):
                raise ConfigurationError(f"entry point '{ep.name}' is not a Tool subclass")
            if tool.name not in self._tools:
                self.register(tool, toolset="plugins")


def required_permissions(tools: list[ToolClass]) -> set[Permission]:
    return {perm for tool in tools for perm in tool.permissions}


_default: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    """The process-wide registry with all built-in tools (and plugins) loaded."""
    global _default
    if _default is None:
        from agentforge.tools.builtin import register_builtin_tools

        registry = ToolRegistry()
        register_builtin_tools(registry)
        registry.load_entry_points()
        _default = registry
    return _default
