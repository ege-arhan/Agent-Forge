"""Agent versions, the storage-backed improvement loop and dogfood suite validity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from agentforge.benchmarks import BenchmarkRunner, load_suite
from agentforge.benchmarks.runner import ResultClass
from agentforge.config_files import load_agent_config
from agentforge.core.errors import ImprovementError, NotFoundError
from agentforge.core.models import AgentVersionSource
from agentforge.improvement import CycleStatus, ProposedChange, Verdict
from agentforge.improvement.cli import run_cycles
from agentforge.improvement.loop import ImprovementLoop
from agentforge.settings import Settings
from agentforge.storage import AgentRepository, Database
from agentforge.storage.db import JSONType, UTCDateTime
from agentforge.storage.migrate import upgrade
from agentforge.storage.tracking import StorageRecorder
from tests.conftest import scripted_config

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
DOGFOOD = ROOT / "dogfood"
ROLES = {
    "coding.yaml": "coding.yaml",
    "debugging.yaml": "debugging.yaml",
    "data-analysis.yaml": "data-analysis.yaml",
    "security.yaml": "security-analysis.yaml",
    "issues.yaml": "github-issue-solver.yaml",
    "hard.yaml": "engineer.yaml",
}


# ----------------------------------------------------------------- versions
async def test_agent_versions_are_recorded(db: Database) -> None:
    repo = AgentRepository(db)
    config = scripted_config([], name="versioned")
    agent = await repo.create(config, change_summary="first")
    same = await repo.update(agent.id, config)
    assert same.version == 1  # identical config: no new version
    changed = await repo.update(
        agent.id, config.model_copy(update={"description": "v2"}), change_summary="describe"
    )
    assert changed.version == 2
    registered = await repo.register(config.model_copy(update={"description": "v3"}))
    assert registered.id == agent.id and registered.version == 3

    versions = await repo.versions(agent.id)
    assert [v.version for v in versions] == [3, 2, 1]
    assert versions[-1].source == AgentVersionSource.CREATED
    assert versions[-1].change_summary == "first"
    assert versions[1].source == AgentVersionSource.UPDATED and versions[1].parent_version == 1
    assert (await repo.get_version(agent.id, 2)).config.description == "v2"
    assert (await repo.resolve("versioned")).id == agent.id
    with pytest.raises(NotFoundError):
        await repo.get_version(agent.id, 9)
    await repo.delete(agent.id)
    with pytest.raises(NotFoundError):
        await repo.versions(agent.id)


async def test_concurrent_agent_updates_get_distinct_versions(db: Database) -> None:
    """Regression: parallel updates must not collide on (agent_id, version)."""
    repo = AgentRepository(db)
    config = scripted_config([], name="racy")
    agent = await repo.create(config)
    updates = [
        repo.update(agent.id, config.model_copy(update={"description": f"d{i}"})) for i in range(6)
    ]
    results = await asyncio.gather(*updates)
    assert sorted(a.version for a in results) == [2, 3, 4, 5, 6, 7]
    assert [v.version for v in await repo.versions(agent.id)] == [7, 6, 5, 4, 3, 2, 1]


async def test_migration_backfills_versions_and_result_class(settings: Settings) -> None:
    db = Database(settings.resolved_database_url)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    agents = sa.table(
        "agents",
        *(sa.column(c) for c in ("id", "name", "description", "version")),
        sa.column("config", JSONType),
        sa.column("created_at", UTCDateTime()),
        sa.column("updated_at", UTCDateTime()),
    )
    benches = sa.table(
        "benchmark_runs",
        *(
            sa.column(c)
            for c in ("id", "suite_id", "suite_name", "agent_name", "status", "repeats")
        ),
        *(sa.column(c, JSONType) for c in ("agent_config", "suite", "results", "environment")),
        sa.column("created_at", UTCDateTime()),
    )
    try:
        await upgrade(db, "0001")
        async with db.engine.begin() as conn:
            for agent_id, provider, version in (
                ("agt_s", "scripted", 1),
                ("agt_r", "anthropic", 3),
            ):
                cfg = {"name": agent_id, "model": {"provider": provider}}
                await conn.execute(
                    agents.insert().values(
                        id=agent_id,
                        name=agent_id,
                        description="",
                        version=version,
                        config=cfg,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await conn.execute(
                    benches.insert().values(
                        id=f"bench_{provider}",
                        suite_id="s",
                        suite_name="s",
                        agent_name=agent_id,
                        status="succeeded",
                        repeats=1,
                        agent_config=cfg,
                        suite={},
                        results=[],
                        environment={},
                        created_at=now,
                    )
                )
        await upgrade(db)
        async with db.engine.connect() as conn:
            versions = (
                await conn.execute(
                    sa.text(
                        "SELECT agent_id, version, source FROM agent_versions ORDER BY agent_id"
                    )
                )
            ).all()
            classes = dict(
                (await conn.execute(sa.text("SELECT id, result_class FROM benchmark_runs"))).all()
            )
        assert [tuple(v) for v in versions] == [("agt_r", 3, "updated"), ("agt_s", 1, "created")]
        assert classes == {"bench_scripted": "offline", "bench_anthropic": "real"}
    finally:
        await db.dispose()


# --------------------------------------------------------------------- loop
async def _baseline(db: Database, settings: Settings, repeats: int = 2) -> tuple[str, str]:
    config = load_agent_config(DOGFOOD / "agents" / "offline" / "demo-coder-v1.yaml")
    agent = await AgentRepository(db).register(config)
    bench = await BenchmarkRunner(settings, recorder=StorageRecorder(db)).run(
        load_suite(DOGFOOD / "benchmarks" / "coding.yaml"),
        config,
        repeats=repeats,
        agent_id=agent.id,
        agent_version=agent.version,
    )
    return agent.id, bench.id


def _runner(db: Database, settings: Settings) -> BenchmarkRunner:
    return BenchmarkRunner(settings, recorder=StorageRecorder(db))


async def test_full_improvement_cycle_preserves_history(db: Database, settings: Settings) -> None:
    agent_id, bench_id = await _baseline(db, settings)
    loop = ImprovementLoop(db)

    analysis = await loop.analyze(bench_id)
    assert analysis.categories == {"step_limit": 4}
    assert analysis.result_class == ResultClass.OFFLINE

    cycle = await loop.propose(bench_id)
    assert cycle.status == CycleStatus.PROPOSED and cycle.from_version == 1
    assert [c.path for c in cycle.proposal.changes] == ["limits.max_steps"]
    assert cycle.task_ids == ["implement-slugify", "add-cli-flag"] and cycle.repeats == 2

    cycle = await loop.apply(cycle.id)
    assert cycle.status == CycleStatus.APPLIED and cycle.to_version == 2
    version = await loop.agents.get_version(agent_id, 2)
    assert version.source == AgentVersionSource.IMPROVEMENT
    assert version.improvement_id == cycle.id and version.config.limits.max_steps == 20
    assert "limits.max_steps: 3 -> 20" in version.change_summary
    with pytest.raises(ImprovementError, match="not proposed"):
        await loop.apply(cycle.id)

    cycle = await loop.evaluate(cycle.id, _runner(db, settings))
    assert cycle.status == CycleStatus.EVALUATED
    assert cycle.comparison is not None
    assert cycle.comparison.verdict == Verdict.IMPROVED  # 0/4 vs 4/4: CIs do not overlap
    assert cycle.comparison.pass_rate_delta == 1.0
    assert {t.change.value for t in cycle.comparison.tasks} == {"fixed"}
    assert cycle.comparison.categories[0].category == "step_limit"
    candidate = await loop.benchmarks.get(cycle.candidate_benchmark_run_id or "")
    assert (candidate.agent_id, candidate.agent_version) == (agent_id, 2)
    assert candidate.suite == (await loop.benchmarks.get(bench_id)).suite

    # Reject after evaluation: baseline config is restored as a *new* version.
    cycle = await loop.reject(cycle.id, "prefer the old budget")
    assert cycle.status == CycleStatus.REJECTED and cycle.reverted_to_version == 3
    versions = await loop.agents.versions(agent_id)
    assert [(v.version, v.source) for v in versions] == [
        (3, AgentVersionSource.REVERT),
        (2, AgentVersionSource.IMPROVEMENT),
        (1, AgentVersionSource.CREATED),
    ]
    assert versions[0].config.limits.max_steps == 3
    with pytest.raises(ImprovementError):
        await loop.reject(cycle.id)
    history = await loop.benchmarks.list(agent_id=agent_id)
    assert {b.agent_version for b in history} == {1, 2}
    assert [c.id for c in await loop.cycles.list(agent_id=agent_id)] == [cycle.id]


async def test_improvement_guards(db: Database, settings: Settings) -> None:
    agent_id, bench_id = await _baseline(db, settings, repeats=1)
    loop = ImprovementLoop(db)

    # Ad-hoc benchmarks (no stored agent version) cannot start a cycle.
    config = load_agent_config(DOGFOOD / "agents" / "offline" / "coding.yaml")
    adhoc = await _runner(db, settings).run(
        load_suite(DOGFOOD / "benchmarks" / "coding.yaml"), config
    )
    with pytest.raises(ImprovementError, match="stored agent version"):
        await loop.propose(adhoc.id)

    # Manual proposal, then the agent changes before it is applied.
    cycle = await loop.propose(
        bench_id,
        changes=[ProposedChange(path="limits.max_steps", value=12, rationale="manual")],
        notes="developer idea",
    )
    assert cycle.proposal.proposer == "manual" and cycle.notes == "developer idea"
    with pytest.raises(ImprovementError, match="unknown change"):
        await loop.apply(cycle.id, ["c9"])
    with pytest.raises(ImprovementError, match="not applied"):
        await loop.start_evaluation(cycle.id)
    agent = await loop.agents.get(agent_id)
    await loop.agents.update(agent_id, agent.config.model_copy(update={"description": "edit"}))
    with pytest.raises(ImprovementError, match="changed since the baseline"):
        await loop.apply(cycle.id)
    rejected = await loop.reject(cycle.id)
    assert rejected.status == CycleStatus.REJECTED and rejected.reverted_to_version is None
    with pytest.raises(ImprovementError, match="cannot be changed"):
        await loop.propose(bench_id, changes=[ProposedChange(path="model.base_url", value="x")])


async def test_run_cycles_stops_when_nothing_to_improve(db: Database, settings: Settings) -> None:
    _, bench_id = await _baseline(db, settings, repeats=3)
    cycles = await run_cycles(db, bench_id, cycles=3, runner=_runner(db, settings))
    assert len(cycles) == 1  # v2 passes everything: no further cycle
    [cycle] = cycles
    assert cycle.comparison is not None and cycle.comparison.verdict == Verdict.IMPROVED
    again = await run_cycles(
        db, cycle.candidate_benchmark_run_id or "", cycles=1, runner=_runner(db, settings)
    )
    assert again[0].proposal.changes == [] and again[0].status == CycleStatus.PROPOSED


# ------------------------------------------------------------------ dogfood
@pytest.mark.parametrize("suite_file", sorted(ROLES))
async def test_dogfood_tasks_are_solvable_and_checks_reject_initial_state(
    settings: Settings, suite_file: str
) -> None:
    """Every dogfood task: the reference solution passes, doing nothing fails."""
    suite = load_suite(DOGFOOD / "benchmarks" / suite_file)
    runner = BenchmarkRunner(settings)
    reference = load_agent_config(DOGFOOD / "agents" / "offline" / ROLES[suite_file])
    solved = await runner.run(suite, reference)
    assert solved.summary is not None
    failing = [r.task_id for r in solved.results if not r.passed]
    assert not failing, f"reference solutions fail: {failing}"

    idle = scripted_config([{"text": "Done."}], name="idle", tools=["filesystem"])
    untouched = await runner.run(suite, idle)
    passing = [r.task_id for r in untouched.results if r.passed]
    assert not passing, f"checks accept the untouched initial state: {passing}"


def test_dogfood_real_agents_match_suites() -> None:
    for suite_file, agent_file in ROLES.items():
        suite = load_suite(DOGFOOD / "benchmarks" / suite_file)
        real = load_agent_config(DOGFOOD / "agents" / agent_file)
        assert real.model.provider != "scripted"
        assert real.labels["program"] == "dogfood"
        for task in suite.tasks:
            assert set(task.allowed_tools or []) <= set(real.tools), (agent_file, task.id)
            assert any(e.type == "completed" for e in task.evaluators), task.id


async def test_interrupted_evaluations_are_failed_on_startup(
    db: Database, settings: Settings
) -> None:
    from agentforge.service import AgentForgeService

    _, bench_id = await _baseline(db, settings, repeats=1)
    loop = ImprovementLoop(db)
    cycle = await loop.apply((await loop.propose(bench_id)).id)
    cycle, bench, _ = await loop.start_evaluation(cycle.id)  # process "dies" here
    assert cycle.status == CycleStatus.EVALUATING

    await AgentForgeService(settings, db).startup()

    failed = await loop.cycles.get(cycle.id)
    assert failed.status == CycleStatus.FAILED and "restarted" in (failed.error or "")
    assert (await loop.benchmarks.get(bench.id)).status.value == "failed"
    rejected = await loop.reject(cycle.id, "retry later")  # no longer stuck
    assert rejected.reverted_to_version == 3
