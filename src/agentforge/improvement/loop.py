"""Storage-backed improvement loop, shared by the CLI and the API service.

Lifecycle of a cycle::

    propose(benchmark of vN)  -> PROPOSED   analysis + proposal recorded
    apply(changes)            -> APPLIED    agent vN+1 stored (source=improvement)
    evaluate()                -> EVALUATING benchmark vN+1 on the same suite snapshot
                              -> EVALUATED  comparison vN vs vN+1 recorded
    reject()                  -> REJECTED   (after evaluation: vN's config restored as vN+2)

Nothing is deleted: versions, benchmarks, runs and cycles form the history.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentforge.benchmarks.runner import BenchmarkRun, BenchmarkRunner, environment_info
from agentforge.core.config import AgentConfig
from agentforge.core.errors import ImprovementError
from agentforge.core.ids import utcnow
from agentforge.core.models import AgentVersionSource, Run, RunStatus
from agentforge.improvement.analysis import FailureAnalysis, analyze
from agentforge.improvement.comparison import BenchmarkComparison, compare_benchmarks
from agentforge.improvement.cycle import CycleStatus, ImprovementCycle
from agentforge.improvement.proposal import (
    ProposedChange,
    apply_changes,
    describe,
    prepare_manual,
    propose,
)
from agentforge.storage.db import Database
from agentforge.storage.repositories import AgentRepository, RunRepository
from agentforge.storage.tracking import BenchmarkRepository, ImprovementRepository

if TYPE_CHECKING:
    from agentforge.policy import ServerPolicy

logger = logging.getLogger("agentforge.improvement")


class ImprovementLoop:
    def __init__(self, db: Database, *, policy: ServerPolicy | None = None) -> None:
        self.agents = AgentRepository(db)
        self.runs = RunRepository(db)
        self.benchmarks = BenchmarkRepository(db)
        self.cycles = ImprovementRepository(db)
        self.policy = policy

    # ---------------------------------------------------------------- analysis
    async def _runs_of(self, bench: BenchmarkRun) -> dict[str, Run]:
        page = await self.runs.list(benchmark_run_id=bench.id, limit=len(bench.results) + 50)
        return {run.id: run for run in page.items}

    async def analyze(self, bench_id: str) -> FailureAnalysis:
        bench = await self.benchmarks.get(bench_id)
        return analyze(bench, await self._runs_of(bench))

    async def compare(self, baseline_id: str, candidate_id: str) -> BenchmarkComparison:
        baseline = await self.benchmarks.get(baseline_id)
        candidate = await self.benchmarks.get(candidate_id)
        return compare_benchmarks(
            baseline,
            candidate,
            baseline_analysis=analyze(baseline, await self._runs_of(baseline)),
            candidate_analysis=analyze(candidate, await self._runs_of(candidate)),
        )

    # ---------------------------------------------------------------- proposal
    async def propose(
        self,
        bench_id: str,
        *,
        changes: list[ProposedChange] | None = None,
        notes: str = "",
    ) -> ImprovementCycle:
        """Analyse a finished benchmark of a stored agent version and record a proposal.

        With ``changes`` the proposal is the developer's (validated against the
        allowlist); otherwise the rule-based proposer derives it.
        """
        bench = await self.benchmarks.get(bench_id)
        if not bench.status.is_terminal:
            raise ImprovementError(f"benchmark {bench_id} has not finished ({bench.status.value})")
        if bench.agent_id is None or bench.agent_version is None:
            raise ImprovementError(
                "this benchmark was not run against a stored agent version; run it with a "
                "stored agent (API: agent_id, CLI: bench run --save-agent)"
            )
        agent = await self.agents.get(bench.agent_id)
        analysis = analyze(bench, await self._runs_of(bench))
        config = bench.agent_config
        proposal = (
            prepare_manual(config, changes) if changes else propose(analysis, config, bench.suite)
        )
        task_ids = list(dict.fromkeys(r.task_id for r in bench.results))
        cycle = ImprovementCycle(
            agent_id=agent.id,
            agent_name=agent.name,
            suite_id=bench.suite_id,
            suite_version=bench.suite.version,
            result_class=bench.result_class,
            task_ids=task_ids,
            repeats=bench.repeats,
            from_version=bench.agent_version,
            baseline_benchmark_run_id=bench.id,
            analysis=analysis,
            proposal=proposal,
            notes=notes,
        )
        await self.cycles.save(cycle)
        return cycle

    # ------------------------------------------------------------------- apply
    async def apply(self, cycle_id: str, change_ids: list[str] | None = None) -> ImprovementCycle:
        cycle = await self.cycles.get(cycle_id)
        if cycle.status != CycleStatus.PROPOSED:
            raise ImprovementError(f"cycle {cycle_id} is {cycle.status.value}, not proposed")
        by_id = {c.id: c for c in cycle.proposal.changes}
        if not by_id:
            raise ImprovementError("the proposal contains no changes to apply")
        selected_ids = change_ids or list(by_id)
        unknown = [i for i in selected_ids if i not in by_id]
        if unknown:
            raise ImprovementError(f"unknown change id(s): {', '.join(unknown)}")
        selected = [by_id[i] for i in selected_ids]

        agent = await self.agents.get(cycle.agent_id)
        if agent.version != cycle.from_version:
            raise ImprovementError(
                f"agent {agent.name} changed since the baseline (now v{agent.version}, baseline "
                f"v{cycle.from_version}); benchmark the current version and propose again"
            )
        baseline = await self.benchmarks.get(cycle.baseline_benchmark_run_id)
        new_config = apply_changes(baseline.agent_config, selected)
        if new_config == agent.config:
            raise ImprovementError("the selected changes do not modify the configuration")
        if self.policy is not None:
            self.policy.check_agent(new_config)
        updated = await self.agents.update(
            agent.id,
            new_config,
            change_summary=describe(selected),
            source=AgentVersionSource.IMPROVEMENT,
            improvement_id=cycle.id,
            parent_version=cycle.from_version,
        )
        cycle.to_version = updated.version
        cycle.applied_change_ids = selected_ids
        cycle.status = CycleStatus.APPLIED
        cycle.updated_at = utcnow()
        await self.cycles.save(cycle)
        return cycle

    # ---------------------------------------------------------------- evaluate
    async def start_evaluation(
        self, cycle_id: str
    ) -> tuple[ImprovementCycle, BenchmarkRun, AgentConfig]:
        """Record a pending candidate benchmark for the new version (runs it separately)."""
        cycle = await self.cycles.get(cycle_id)
        if cycle.status != CycleStatus.APPLIED or cycle.to_version is None:
            raise ImprovementError(f"cycle {cycle_id} is {cycle.status.value}, not applied")
        baseline = await self.benchmarks.get(cycle.baseline_benchmark_run_id)
        version = await self.agents.get_version(cycle.agent_id, cycle.to_version)
        config = version.config
        if self.policy is not None:
            self.policy.check_agent(config)
        # Claim the cycle atomically: a concurrent (or retried) evaluate request
        # must not start a second candidate benchmark for the same cycle.
        if not await self.cycles.claim(
            cycle.id, expected=CycleStatus.APPLIED, new=CycleStatus.EVALUATING
        ):
            raise ImprovementError(f"cycle {cycle_id} is already being evaluated")
        bench = BenchmarkRun(
            suite_id=baseline.suite_id,
            suite_name=baseline.suite_name,
            agent_name=config.name,
            agent_config=config,
            suite=baseline.suite,  # the exact suite snapshot of the baseline
            repeats=cycle.repeats,
            environment=environment_info(config),
            agent_id=cycle.agent_id,
            agent_version=cycle.to_version,
        )
        await self.benchmarks.save(bench)
        cycle.candidate_benchmark_run_id = bench.id
        cycle.status = CycleStatus.EVALUATING
        cycle.updated_at = utcnow()
        await self.cycles.save(cycle)
        return cycle, bench, config

    async def finish_evaluation(
        self, cycle: ImprovementCycle, bench: BenchmarkRun | None, error: str | None = None
    ) -> ImprovementCycle:
        if bench is None or error is not None or bench.status != RunStatus.SUCCEEDED:
            cycle.status = CycleStatus.FAILED
            cycle.error = error or (
                f"candidate benchmark ended with status {bench.status.value}"
                if bench
                else "candidate benchmark did not run"
            )
        else:
            baseline = await self.benchmarks.get(cycle.baseline_benchmark_run_id)
            candidate_analysis = analyze(bench, await self._runs_of(bench))
            cycle.comparison = compare_benchmarks(
                baseline,
                bench,
                baseline_analysis=cycle.analysis,
                candidate_analysis=candidate_analysis,
            )
            cycle.status = CycleStatus.EVALUATED
        cycle.updated_at = utcnow()
        await self.cycles.save(cycle)
        return cycle

    async def evaluate(self, cycle_id: str, runner: BenchmarkRunner) -> ImprovementCycle:
        """Benchmark the new version inline and compare it with the baseline."""
        cycle, bench, config = await self.start_evaluation(cycle_id)
        try:
            bench = await runner.run(
                bench.suite,
                config,
                repeats=cycle.repeats,
                task_ids=cycle.task_ids,
                bench=bench,
            )
        except Exception as exc:
            logger.exception("evaluation of improvement cycle %s failed", cycle.id)
            return await self.finish_evaluation(cycle, None, f"{type(exc).__name__}: {exc}")
        return await self.finish_evaluation(cycle, bench)

    # ------------------------------------------------------------------ reject
    async def reject(self, cycle_id: str, reason: str = "") -> ImprovementCycle:
        """Decline a proposal, or revert an applied/evaluated one.

        Reverting never rewrites history: the baseline configuration is stored
        again as a new version (source ``revert``) if the improved version is
        still the agent's current one.
        """
        cycle = await self.cycles.get(cycle_id)
        if cycle.status in (CycleStatus.REJECTED, CycleStatus.EVALUATING):
            raise ImprovementError(f"cycle {cycle_id} is {cycle.status.value}")
        if cycle.to_version is not None:
            agent = await self.agents.get(cycle.agent_id)
            if agent.version == cycle.to_version:
                baseline = await self.agents.get_version(cycle.agent_id, cycle.from_version)
                reverted = await self.agents.update(
                    agent.id,
                    baseline.config,
                    change_summary=f"Reverted improvement {cycle.id}"
                    + (f": {reason}" if reason else ""),
                    source=AgentVersionSource.REVERT,
                    improvement_id=cycle.id,
                    parent_version=cycle.to_version,
                )
                cycle.reverted_to_version = reverted.version
        if reason:
            cycle.notes = f"{cycle.notes}\n{reason}".strip()
        cycle.status = CycleStatus.REJECTED
        cycle.updated_at = utcnow()
        await self.cycles.save(cycle)
        return cycle
