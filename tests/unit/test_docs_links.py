"""Relative links and heading anchors in the Markdown docs resolve."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGES = sorted(
    [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").glob("*.md"),
        ROOT / "dogfood" / "README.md",
    ]
)
LINK = re.compile(r"(?<!\\)\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)


def anchors(page: Path) -> set[str]:
    """GitHub-style slugs of the page's headings."""
    slugs: set[str] = set()
    for line in FENCE.sub("", page.read_text()).splitlines():
        match = re.match(r"#{1,6}\s+(.*)", line)
        if match:
            title = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", match.group(1)).strip().lower()
            slugs.add(re.sub(r"[^\w\- ]", "", title).replace(" ", "-"))
    return slugs


def test_slugs_follow_github_rules(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text("# Quick start (offline, no API key)\n\n```\n# not a heading\n```\n## A → B\n")
    assert anchors(page) == {"quick-start-offline-no-api-key", "a--b"}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(page: Path) -> None:
    broken: list[str] = []
    for target in LINK.findall(FENCE.sub("", page.read_text())):
        if re.match(r"[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto:
            continue
        path, _, fragment = target.partition("#")
        linked = (page.parent / path).resolve() if path else page
        if not linked.exists():
            broken.append(f"{target} (no such file)")
        elif fragment and linked.suffix == ".md" and fragment not in anchors(linked):
            broken.append(f"{target} (no such heading)")
    assert not broken, f"{page.relative_to(ROOT)}: {broken}"
