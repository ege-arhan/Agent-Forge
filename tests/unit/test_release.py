from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import agentforge

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts/release_notes.py")
assert spec and spec.loader
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## [Unreleased]

### Added
- future

## [0.2.0] - 2026-10-01

### Added
- thing one

### Fixed
- bug

## [0.1.0] - 2026-09-01
- first
"""


def test_changelog_section_extraction() -> None:
    notes = release_notes.changelog_section(CHANGELOG, "0.2.0")
    assert notes.startswith("### Added\n- thing one")
    assert "### Fixed\n- bug" in notes
    assert "0.1.0" not in notes and "future" not in notes
    assert release_notes.changelog_section(CHANGELOG, "0.1.0") == "- first\n"
    with pytest.raises(SystemExit):
        release_notes.changelog_section(CHANGELOG, "9.9.9")


def test_version_strings_are_consistent() -> None:
    found = release_notes.versions(ROOT)
    assert set(found.values()) == {agentforge.__version__}, found
