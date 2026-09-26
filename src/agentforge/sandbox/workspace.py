"""Per-run workspace directories with path confinement."""

from __future__ import annotations

import shutil
from pathlib import Path

from agentforge.core.errors import WorkspaceError


class Workspace:
    """A directory that confines an agent's file operations.

    Every user-supplied path is resolved (following symlinks) and must stay
    inside the workspace root; absolute paths and ``..`` escapes are rejected.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create(self) -> Workspace:
        self.root.mkdir(parents=True, exist_ok=True)
        return self

    def resolve(self, path: str | Path = ".") -> Path:
        raw = Path(path)
        # Absolute paths are accepted only if they already point inside the root.
        candidate = raw.resolve() if raw.is_absolute() else (self.root / raw).resolve()
        if candidate != self.root and not candidate.is_relative_to(self.root):
            raise WorkspaceError(f"path '{path}' is outside the workspace")
        return candidate

    def relative(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.root)
        return "." if str(rel) == "." else rel.as_posix()

    def write_files(self, files: dict[str, str]) -> None:
        for rel, content in files.items():
            target = self.resolve(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def destroy(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
