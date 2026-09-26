"""Release helpers: extract notes from CHANGELOG.md and check version consistency.

python scripts/release_notes.py notes 0.2.0     # print the changelog section
python scripts/release_notes.py check 0.2.0     # verify all version strings match
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def changelog_section(text: str, version: str) -> str:
    """Return the body of the ``## [version]`` section (without the heading)."""
    pattern = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", re.M | re.S)
    match = pattern.search(text)
    if not match or not match.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no non-empty section for [{version}]")
    return match.group(1).strip() + "\n"


def versions(root: Path = ROOT) -> dict[str, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    init = re.search(r'__version__ = "([^"]+)"', (root / "src/agentforge/__init__.py").read_text())
    web = json.loads((root / "web/package.json").read_text())["version"]
    return {
        "pyproject.toml": pyproject,
        "src/agentforge/__init__.py": init.group(1) if init else "",
        "web/package.json": web,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("notes", "check"):
        print(__doc__)
        return 2
    command, version = argv[1], argv[2].removeprefix("v")
    if command == "notes":
        sys.stdout.write(changelog_section((ROOT / "CHANGELOG.md").read_text(), version))
        return 0
    mismatched = {k: v for k, v in versions().items() if v != version}
    if mismatched:
        print(f"version mismatch for {version}: {mismatched}")
        return 1
    print(f"all versions are {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
