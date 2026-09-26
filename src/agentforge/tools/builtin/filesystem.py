"""Workspace-confined filesystem tools."""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Any, ClassVar

from pydantic import Field

from agentforge.core.errors import ToolError
from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput

MAX_READ_BYTES = 2_000_000
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache"}


class ReadFileInput(ToolInput):
    path: str = Field(description="File path relative to the workspace root.")
    start_line: int = Field(default=1, ge=1, description="First line to return (1-based).")
    max_lines: int = Field(default=2_000, ge=1, le=20_000)


class ReadFile(Tool[ReadFileInput]):
    name = "read_file"
    description = (
        "Read a UTF-8 text file from the workspace. Returns the requested line range, "
        "each line prefixed with its line number."
    )
    input_model = ReadFileInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.FS_READ})

    async def run(self, args: ReadFileInput, ctx: ToolContext) -> ToolOutput:
        path = ctx.workspace.resolve(args.path)
        if not path.is_file():
            raise ToolError(f"file not found: {args.path}")
        if path.stat().st_size > MAX_READ_BYTES:
            raise ToolError(f"file too large to read ({path.stat().st_size} bytes)")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"file is not valid UTF-8 text: {args.path}") from exc
        lines = text.splitlines()
        start = args.start_line - 1
        selected = lines[start : start + args.max_lines]
        body = "\n".join(f"{start + i + 1:>6}\t{line}" for i, line in enumerate(selected))
        remaining = len(lines) - (start + len(selected))
        if remaining > 0:
            body += (
                f"\n[{remaining} more lines; continue with start_line={start + len(selected) + 1}]"
            )
        return ToolOutput(content=body or "(empty file)", data={"lines": len(lines)})


class WriteFileInput(ToolInput):
    path: str = Field(description="File path relative to the workspace root.")
    content: str = Field(description="Complete new file content.")


class WriteFile(Tool[WriteFileInput]):
    name = "write_file"
    description = (
        "Create or overwrite a text file in the workspace with the given content. "
        "Parent directories are created as needed."
    )
    input_model = WriteFileInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.FS_WRITE})

    async def run(self, args: WriteFileInput, ctx: ToolContext) -> ToolOutput:
        path = ctx.workspace.resolve(args.path)
        if path.is_dir():
            raise ToolError(f"path is a directory: {args.path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.content, encoding="utf-8")
        return ToolOutput(content=f"wrote {len(args.content)} characters to {args.path}")


class EditFileInput(ToolInput):
    path: str
    old_text: str = Field(min_length=1, description="Exact text to replace.")
    new_text: str = Field(description="Replacement text.")
    replace_all: bool = Field(
        default=False, description="Replace every occurrence instead of requiring exactly one."
    )


class EditFile(Tool[EditFileInput]):
    name = "edit_file"
    description = (
        "Replace an exact text snippet in a workspace file. Fails if the snippet is not found, "
        "or is found more than once and replace_all is false."
    )
    input_model = EditFileInput
    permissions: ClassVar[frozenset[Permission]] = frozenset(
        {Permission.FS_READ, Permission.FS_WRITE}
    )

    async def run(self, args: EditFileInput, ctx: ToolContext) -> ToolOutput:
        path = ctx.workspace.resolve(args.path)
        if not path.is_file():
            raise ToolError(f"file not found: {args.path}")
        text = path.read_text(encoding="utf-8")
        count = text.count(args.old_text)
        if count == 0:
            raise ToolError("old_text not found in file")
        if count > 1 and not args.replace_all:
            raise ToolError(f"old_text occurs {count} times; make it unique or set replace_all")
        updated = text.replace(args.old_text, args.new_text, -1 if args.replace_all else 1)
        path.write_text(updated, encoding="utf-8")
        return ToolOutput(content=f"replaced {count if args.replace_all else 1} occurrence(s)")


class ListDirectoryInput(ToolInput):
    path: str = "."
    recursive: bool = False
    max_entries: int = Field(default=500, ge=1, le=5_000)


class ListDirectory(Tool[ListDirectoryInput]):
    name = "list_directory"
    description = (
        "List files and directories in the workspace. Directories end with '/'. "
        "Version-control and dependency folders are skipped when recursive."
    )
    input_model = ListDirectoryInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.FS_READ})

    async def run(self, args: ListDirectoryInput, ctx: ToolContext) -> ToolOutput:
        root = ctx.workspace.resolve(args.path)
        if not root.is_dir():
            raise ToolError(f"not a directory: {args.path}")
        entries: list[str] = []
        truncated = False
        if args.recursive:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
                base = ctx.workspace.relative(ctx.workspace.resolve(dirpath))
                prefix = "" if base == "." else base + "/"
                entries.extend(f"{prefix}{d}/" for d in dirnames)
                entries.extend(f"{prefix}{f}" for f in sorted(filenames))
                if len(entries) >= args.max_entries:
                    truncated = True
                    break
        else:
            for child in sorted(root.iterdir(), key=lambda p: p.name):
                entries.append(child.name + ("/" if child.is_dir() else ""))
        if len(entries) > args.max_entries:
            truncated = True
        entries = entries[: args.max_entries]
        text = "\n".join(entries) or "(empty directory)"
        if truncated:
            text += f"\n[listing truncated at {args.max_entries} entries]"
        return ToolOutput(content=text)


class SearchFilesInput(ToolInput):
    pattern: str = Field(description="Regular expression to search for.")
    path: str = "."
    glob: str | None = Field(default=None, description="Only search files matching, e.g. '*.py'.")
    max_results: int = Field(default=200, ge=1, le=2_000)


class SearchFiles(Tool[SearchFilesInput]):
    name = "search_files"
    description = "Search workspace text files for a regular expression; returns path:line: text."
    input_model = SearchFilesInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.FS_READ})

    async def run(self, args: SearchFilesInput, ctx: ToolContext) -> ToolOutput:
        try:
            regex = re.compile(args.pattern)
        except re.error as exc:
            raise ToolError(f"invalid regular expression: {exc}") from exc
        root = ctx.workspace.resolve(args.path)
        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for filename in sorted(filenames):
                if args.glob and not fnmatch.fnmatch(filename, args.glob):
                    continue
                file_path = ctx.workspace.resolve(os.path.join(dirpath, filename))
                try:
                    if file_path.stat().st_size > MAX_READ_BYTES:
                        continue
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                rel = ctx.workspace.relative(file_path)
                for number, line in enumerate(lines, start=1):
                    if regex.search(line):
                        results.append(f"{rel}:{number}: {line.strip()[:300]}")
                        if len(results) >= args.max_results:
                            return ToolOutput(content="\n".join(results) + "\n[results truncated]")
        return ToolOutput(content="\n".join(results) or "no matches")


FILESYSTEM_TOOLS: list[type[Tool[Any]]] = [
    ReadFile,
    WriteFile,
    EditFile,
    ListDirectory,
    SearchFiles,
]
