"""The ``dogfood-swe`` suite's hidden checks reject plausible wrong solutions.

The reference solutions pass and an idle agent fails every task
(``test_improvement_loop.py``). Here each task gets solutions that look right
- the tests in the workspace pass - but miss what a hidden check or the
repository's original tests are there to catch, and exactly those checks
must fail.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from agentforge.benchmarks import BenchmarkRunner, load_suite
from agentforge.config_files import load_agent_config
from agentforge.settings import Settings
from agentforge.storage import Database, RunRepository
from agentforge.storage.tracking import StorageRecorder
from tests.conftest import scripted_config

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SUITE = load_suite(ROOT / "dogfood" / "benchmarks" / "swe.yaml")
REFERENCE = load_agent_config(ROOT / "dogfood" / "agents" / "offline" / "swe.yaml")
DRIFT, CONFLICTS, SKIP = "month-end-drift", "conflict-report", "skip-dates"
WHEN = {
    DRIFT: "moves to the 28th",
    CONFLICTS: "conflict report is wrong",
    SKIP: "Skip single dates",
}


def reference_turns(task_id: str) -> list[dict[str, Any]]:
    rules = REFERENCE.model.options["rules"]
    turns: list[dict[str, Any]] = next(r["turns"] for r in rules if r["when"] == WHEN[task_id])
    return copy.deepcopy(turns)


def _writes(turn: dict[str, Any], path: str) -> bool:
    return any(
        call["name"] == "write_file" and call["arguments"]["path"] == path
        for call in turn.get("tool_calls", [])
    )


def replace_write(turns: list[dict[str, Any]], path: str, old: str, new: str) -> None:
    """Edit the content a reference turn writes to ``path``."""
    for turn in turns:
        if _writes(turn, path):
            [call] = turn["tool_calls"]
            content = call["arguments"]["content"]
            assert content.count(old) == 1, (path, old)
            call["arguments"] = {**call["arguments"], "content": content.replace(old, new)}
            return
    raise AssertionError(f"no write to {path}")


def drop_write(turns: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    kept = [turn for turn in turns if not _writes(turn, path)]
    assert len(kept) == len(turns) - 1, path
    return kept


def command(text: str) -> dict[str, Any]:
    return {
        "text": "Running a command.",
        "tool_calls": [{"name": "run_command", "arguments": {"command": text}}],
    }


async def checks(
    settings: Settings, db: Database, task_id: str, turns: list[dict[str, Any]]
) -> dict[str, bool]:
    """Per-check outcome of one run of ``task_id`` replaying ``turns``."""
    config = scripted_config(turns, name="variant", tools=["filesystem", "terminal"])
    config = config.model_copy(update={"sandbox": REFERENCE.sandbox})
    runner = BenchmarkRunner(settings, recorder=StorageRecorder(db))
    bench = await runner.run(SUITE, config, task_ids=[task_id])
    [result] = bench.results
    run = await RunRepository(db).get(result.run_id)
    assert run.evaluation is not None
    return {c.name: c.passed for c in run.evaluation.results}


def failing(result: dict[str, bool]) -> set[str]:
    return {name for name, passed in result.items() if not passed}


# ------------------------------------------------------------------- suite
def test_every_task_starts_from_the_same_repository() -> None:
    first, *others = SUITE.tasks
    assert len(first.setup.files) >= 15
    for task in others:
        assert task.setup.files == first.setup.files
        assert task.setup.git_init
    for task in SUITE.tasks:
        names = [e.name for e in task.evaluators]
        assert {"unit_tests", "existing_tests"} <= set(names)
        assert sum(name.startswith("hidden_") for name in names) >= 3
        # The goal is an issue: it must not give the hidden checks away.
        assert "hidden" not in task.goal.lower()


async def test_the_untouched_repository_passes_its_own_tests_and_fails_every_hidden_fix_check(
    settings: Settings, db: Database
) -> None:
    """The visible tests do not cover the issues: only hidden checks tell fixed from unfixed."""
    idle = [command("python3 -m unittest discover -s tests"), {"text": "Nothing to do."}]
    for task_id in (DRIFT, CONFLICTS, SKIP):
        result = await checks(settings, db, task_id, idle)
        assert result["unit_tests"] and result["existing_tests"], task_id
        expected = {name for name in result if name.startswith("hidden_")} - {"hidden_unchanged"}
        assert failing(result) == expected, task_id


# -------------------------------------------------------------- month end
async def test_drift_fixed_in_the_expansion_only_fails_the_next_occurrence_check(
    settings: Settings, db: Database
) -> None:
    # agenda.next_occurrence has its own copy of the stepping; the issue names the command.
    turns = drop_write(reference_turns(DRIFT), "flowcal/agenda.py")
    assert failing(await checks(settings, db, DRIFT, turns)) == {"hidden_next"}


async def test_drift_fixed_for_months_but_not_years_fails_the_leap_day_checks(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(DRIFT)
    replace_write(
        turns,
        "flowcal/recurrence.py",
        "    return add_months(start, 12 * step)\n",
        "    for _ in range(index):\n"
        "        start = add_months(start, 12 * rule.interval)\n"
        "    return start\n",
    )
    result = await checks(settings, db, DRIFT, turns)
    assert failing(result) == {"hidden_leap_day", "hidden_next"}


async def test_drift_fixed_by_editing_the_data_fails(settings: Settings, db: Database) -> None:
    turns = [
        command(
            'sed -i \'s/"start": "2026-01-31T16:00"/"start": "2026-01-28T16:00"/\' calendar.json'
        ),
        {"text": "Moved the event to the 28th so it no longer drifts."},
    ]
    result = await checks(settings, db, DRIFT, turns)
    assert {"data_untouched", "hidden_month_end", "hidden_next"} <= failing(result)


# -------------------------------------------------------------- conflicts
async def test_conflicts_still_comparing_neighbours_only_fails_the_pair_checks(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(CONFLICTS)
    replace_write(
        turns,
        "flowcal/agenda.py",
        "    for index, first in enumerate(items):\n"
        "        for second in items[index + 1 :]:\n"
        "            if second.start >= first.end:\n"
        "                break  # sorted by start: nothing later reaches into `first`\n"
        "            if overlaps(first, second):\n"
        "                pairs.append((first, second))\n",
        "    for first, second in zip(items, items[1:]):\n"
        "        if overlaps(first, second):\n"
        "            pairs.append((first, second))\n",
    )
    result = await checks(settings, db, CONFLICTS, turns)
    assert failing(result) == {"hidden_all_pairs", "hidden_cli"}


async def test_conflicts_window_fix_that_loses_reminders_fails_only_the_window_check(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(CONFLICTS)
    # "Ends after the window opens" is the obvious rule; a zero-length reminder
    # at the window's first minute ends exactly when it opens.
    replace_write(
        turns,
        "flowcal/recurrence.py",
        "if start >= window_start or occurrence.end > window_start:",
        "if occurrence.end > window_start:",
    )
    assert failing(await checks(settings, db, CONFLICTS, turns)) == {"hidden_window_start"}


async def test_conflicts_without_the_window_fix_fails_the_window_and_cli_checks(
    settings: Settings, db: Database
) -> None:
    turns = drop_write(reference_turns(CONFLICTS), "flowcal/recurrence.py")
    result = await checks(settings, db, CONFLICTS, turns)
    assert failing(result) == {"hidden_window_start", "hidden_cli"}


# ------------------------------------------------------------------- skip
async def test_skip_not_counting_skipped_dates_fails_only_the_expansion_check(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(SKIP)
    # Filtering before counting: a `count: 5` series then runs until it has
    # produced five occurrences that are not skipped.
    replace_write(
        turns,
        "flowcal/recurrence.py",
        "        yield current\n        produced += 1\n",
        "        if current.date() in event.skip:\n"
        "            continue\n"
        "        yield current\n"
        "        produced += 1\n",
    )
    assert failing(await checks(settings, db, SKIP, turns)) == {"hidden_expansion"}


async def test_skip_command_that_accepts_any_date_fails_only_the_cli_check(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(SKIP)
    replace_write(turns, "flowcal/cli.py", "if not _happens_on(event, day):", "if False:")
    assert failing(await checks(settings, db, SKIP, turns)) == {"hidden_cli"}


async def test_skip_changing_the_file_format_is_caught_even_if_the_agent_drops_the_test(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(SKIP)
    # Always writing the key changes every saved calendar...
    replace_write(turns, "flowcal/store.py", "    if event.skip:\n", "    if True:\n")
    # ...and removing the test that says so makes the workspace's tests green.
    turns.insert(-2, command("rm tests/test_store.py"))
    result = await checks(settings, db, SKIP, turns)
    assert result["unit_tests"]
    assert failing(result) == {"existing_tests", "hidden_model_store", "hidden_cli"}
