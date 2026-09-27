"""The hard dogfood suite's hidden and process checks reject plausible wrong solutions.

The reference solutions pass and an idle agent fails every task
(``test_improvement_loop.py``). Here each task gets a solution that looks
right - its visible tests pass - but misses exactly what a hidden or process
check is there to catch, and that check (only that one) must fail.
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
SUITE = load_suite(ROOT / "dogfood" / "benchmarks" / "hard.yaml")
REFERENCE = load_agent_config(ROOT / "dogfood" / "agents" / "offline" / "engineer.yaml")


def reference_turns(marker: str) -> list[dict[str, Any]]:
    rules = REFERENCE.model.options["rules"]
    turns: list[dict[str, Any]] = next(r["turns"] for r in rules if r["when"] == marker)
    return copy.deepcopy(turns)


def replace_write(turns: list[dict[str, Any]], path: str, old: str, new: str) -> None:
    """Edit the content a reference turn writes to ``path``."""
    for turn in turns:
        for call in turn.get("tool_calls", []):
            if call["name"] == "write_file" and call["arguments"]["path"] == path:
                content = call["arguments"]["content"]
                assert old in content, (path, old)
                call["arguments"] = {**call["arguments"], "content": content.replace(old, new)}
                return
    raise AssertionError(f"no write to {path}")


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


async def test_coupons_banker_rounding_fails_only_the_hidden_api_check(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(r"SPEC\.md")
    # round() rounds half to even: 100.5 -> 100 instead of the specified half-up 101.
    replace_write(
        turns,
        "shop/coupons.py",
        "return (subtotal * coupon.value + 50) // 100",
        "return round(subtotal * coupon.value / 100)",
    )
    # ...and its own test agrees with it, so every visible check passes.
    replace_write(
        turns,
        "tests/test_coupons.py",
        'self.assertEqual(totals["discount"], 101)',
        'self.assertEqual(totals["discount"], 100)',
    )
    assert failing(await checks(settings, db, "coupons-feature", turns)) == {"hidden_api"}


async def test_coupons_changed_result_shape_fails_existing_behaviour(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(r"SPEC\.md")
    replace_write(
        turns,
        "shop/pricing.py",
        'return {"subtotal": subtotal, "tax": tax, "total": subtotal + tax}',
        'return {"subtotal": subtotal, "discount": 0, "tax": tax, "total": subtotal + tax}',
    )
    result = await checks(settings, db, "coupons-feature", turns)
    assert {"unit_tests", "hidden_api"} <= failing(result)


async def test_ledger_one_regression_test_for_two_causes_fails(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(r"BUG\.md")
    replace_write(
        turns,
        "tests/test_parser.py",
        '        self.assertEqual(parse_amount("19.99"), 1999)\n'
        '        self.assertEqual(parse_amount("-0.29"), -29)\n',
        "        pass\n",
    )
    result = await checks(settings, db, "ledger-root-causes", turns)
    assert failing(result) == {"regression_test_per_root_cause"}


async def test_ledger_fixing_only_the_csv_split_fails(settings: Settings, db: Database) -> None:
    turns = reference_turns(r"BUG\.md")
    replace_write(
        turns,
        "ledger/parser.py",
        '    text = text.replace(",", "").strip()\n',
        '    return int(float(text.replace(",", "")) * 100)\n',
    )
    result = await checks(settings, db, "ledger-root-causes", turns)
    assert {"report_correct", "hidden_edge_cases", "unit_tests"} <= failing(result)


async def test_git_manual_fix_instead_of_revert_fails(settings: Settings, db: Database) -> None:
    turns = reference_turns(r"TASK\.md")
    manual = (
        "bad=$(git log --format=%H --grep='^Speed up median$') "
        "&& sed -i 's/    values.sort()  # sort in place: avoids a copy/    s = sorted(values)/; "
        "/^    s = values$/d' stats.py "
        "&& git commit -q -am 'Fix median' && echo \"$bad\" > BAD_COMMIT.txt "
        "&& git add BAD_COMMIT.txt && git commit -q -m 'Record the commit that broke median'"
    )
    for turn in turns:
        for call in turn.get("tool_calls", []):
            if "git revert" in call["arguments"].get("command", ""):
                call["arguments"] = {"command": manual}
    result = await checks(settings, db, "git-regression-hunt", turns)
    assert result["check_passes"] and result["bad_commit_identified"]
    assert failing(result) == {"reverted_with_git_revert"}


async def test_git_reset_loses_history_and_later_changes(settings: Settings, db: Database) -> None:
    turns = [
        {
            "text": "Resetting to before the bad commit.",
            "tool_calls": [
                {
                    "name": "run_command",
                    "arguments": {
                        "command": "git reset -q --hard HEAD~4 && git log --format=%H -n1 > "
                        "BAD_COMMIT.txt && git add BAD_COMMIT.txt && git commit -q -m record"
                    },
                }
            ],
        },
        {
            "text": "Checking.",
            "tool_calls": [{"name": "run_command", "arguments": {"command": "ls"}}],
        },
        {"text": "Done."},
    ]
    result = await checks(settings, db, "git-regression-hunt", turns)
    assert {"history_preserved", "later_changes_kept", "bad_commit_identified"} <= failing(result)


async def test_settings_unconverted_env_values_fail_only_hidden_env_rules(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(r"CHANGE\.md")
    replace_write(turns, "settings.py", "settings[key] = convert(raw)", "settings[key] = raw")
    replace_write(
        turns,
        "tests/test_settings.py",
        '(9100, True, "x")',
        '("9100", "yes", "x")',
    )
    assert failing(await checks(settings, db, "env-overrides", turns)) == {"hidden_env_rules"}


async def test_settings_rewritten_comment_rule_fails_existing_behaviour(
    settings: Settings, db: Database
) -> None:
    turns = reference_turns(r"CHANGE\.md")
    # A "cleanup" that treats every '#' as a comment breaks documented values like URLs.
    replace_write(
        turns,
        "settings.py",
        '        if " #" in stripped:\n            stripped = stripped[: stripped.index(" #")].rstrip()',
        '        stripped = stripped.split("#")[0].rstrip()',
    )
    result = await checks(settings, db, "env-overrides", turns)
    assert failing(result) == {"hidden_existing_behaviour"}
