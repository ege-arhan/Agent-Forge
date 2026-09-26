"""Built-in tools, grouped into toolsets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentforge.tools.builtin.filesystem import FILESYSTEM_TOOLS
from agentforge.tools.builtin.git import GIT_TOOLS
from agentforge.tools.builtin.github import GITHUB_TOOLS
from agentforge.tools.builtin.http import HTTP_TOOLS
from agentforge.tools.builtin.memory import MEMORY_TOOLS
from agentforge.tools.builtin.terminal import TERMINAL_TOOLS

if TYPE_CHECKING:
    from agentforge.tools.registry import ToolRegistry

TOOLSETS = {
    "filesystem": FILESYSTEM_TOOLS,
    "terminal": TERMINAL_TOOLS,
    "git": GIT_TOOLS,
    "http": HTTP_TOOLS,
    "github": GITHUB_TOOLS,
    "memory": MEMORY_TOOLS,
}


def register_builtin_tools(registry: ToolRegistry) -> None:
    for toolset, tools in TOOLSETS.items():
        for tool in tools:
            registry.register(tool, toolset=toolset)
