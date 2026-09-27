"use client";

import { Check, FlaskConical, Lightbulb, Play, Undo2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { RateWithInterval } from "@/components/bars";
import { CategoryBars, CycleStatusBadge, ResultClassBadge, VerdictBadge } from "@/components/improvement";
import { PageHeader } from "@/components/page-header";
import { RunStatusBadge } from "@/components/status";
import { Empty, ErrorState, Loading } from "@/components/states";
import { StatTile } from "@/components/stat-tile";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatDelta, formatNumber, isTerminal, relativeTime } from "@/lib/format";
import {
  categoryLabel,
  configDiff,
  cycleActions,
  describeChange,
  formatValue,
  gateDisplay,
  resultClassOf,
  splitByResultClass,
} from "@/lib/improvement";
import type { AgentVersion, BenchmarkRun, ImprovementCycle, ResultClass } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function useAction(reload: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await action();
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function BenchmarkTable({
  runs,
  selected,
  onSelect,
}: {
  runs: BenchmarkRun[];
  selected: string | undefined;
  onSelect: (id: string) => void;
}) {
  if (runs.length === 0) return <Empty>No benchmark runs in this class.</Empty>;
  return (
    <Table>
      <THead>
        <TR>
          <TH>When</TH>
          <TH>Version</TH>
          <TH>Suite</TH>
          <TH>Status</TH>
          <TH>Pass rate (95% CI)</TH>
          <TH className="text-right">Mean steps</TH>
          <TH />
        </TR>
      </THead>
      <TBody>
        {runs.map((b) => (
          <TR key={b.id} className={b.id === selected ? "bg-surface-2" : undefined}>
            <TD className="text-xs text-ink-2">
              <Link href={`/benchmarks/${b.id}`} className="hover:underline">
                {relativeTime(b.created_at)}
              </Link>
            </TD>
            <TD className="tabular">{b.agent_version ? `v${b.agent_version}` : "—"}</TD>
            <TD className="font-mono text-xs whitespace-nowrap">
              {b.suite_id}@{b.suite.version}
              {b.experiment_id ? (
                <Link href={`/experiments/${b.experiment_id}`} className="ml-1 text-muted hover:underline">
                  (experiment)
                </Link>
              ) : null}
            </TD>
            <TD>
              <RunStatusBadge status={b.status} />
            </TD>
            <TD>
              {b.summary ? (
                <RateWithInterval rate={b.summary.pass_rate} interval={b.summary.pass_rate_ci95} />
              ) : (
                <span className="text-xs text-muted">running…</span>
              )}
            </TD>
            <TD className="tabular text-right">{formatNumber(b.summary?.mean_steps)}</TD>
            <TD className="text-right">
              <Button size="sm" variant="ghost" onClick={() => onSelect(b.id)} disabled={!isTerminal(b.status)}>
                Analyse
              </Button>
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function AnalysisPanel({
  benchId,
  canPropose,
  onProposed,
}: {
  benchId: string;
  canPropose: boolean;
  onProposed: () => void;
}) {
  const analysis = useApi(() => api.benchmarkAnalysis(benchId), [benchId]);
  const action = useAction(onProposed);
  if (analysis.error) return <p className="px-4 py-3 text-xs text-critical-text">{analysis.error}</p>;
  if (!analysis.data) return <Loading />;
  const a = analysis.data;
  return (
    <CardBody className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-ink-2">
          {a.suite_id}@{a.suite_version} · v{a.agent_version ?? "?"} · {a.passed}/{a.runs} passed ·{" "}
          <ResultClassBadge value={a.result_class} />
        </p>
        <Button
          size="sm"
          disabled={!canPropose || action.busy}
          title={canPropose ? undefined : "Only benchmarks of stored agent versions can start a cycle"}
          onClick={() => action.run(() => api.proposeImprovement({ benchmark_run_id: a.benchmark_run_id }))}
        >
          <Lightbulb aria-hidden className="size-3.5" /> Propose improvement
        </Button>
      </div>
      {action.error ? <p className="text-xs text-critical-text">{action.error}</p> : null}
      <div>
        <h3 className="mb-2 text-xs font-medium text-ink-2">Failure categories</h3>
        <CategoryBars counts={a.categories} />
      </div>
      {a.failures.length ? (
        <div>
          <h3 className="mb-2 text-xs font-medium text-ink-2">Failed runs</h3>
          <ul className="space-y-2">
            {a.failures.map((f) => (
              <li key={f.run_id} className="rounded-md border border-line px-3 py-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
                  <span>
                    <span className="font-mono text-xs">{f.task_id}</span> #{f.repeat} ·{" "}
                    <span className="font-medium">{categoryLabel(f.category)}</span>
                    {f.secondary.length ? (
                      <span className="text-muted"> (+ {f.secondary.map(categoryLabel).join(", ")})</span>
                    ) : null}
                  </span>
                  <Link href={`/runs/${f.run_id}`} className="font-mono text-xs text-muted hover:underline">
                    {f.run_id}
                  </Link>
                </div>
                {f.evidence.slice(0, 3).map((line, i) => (
                  <p key={i} className="mt-1 font-mono text-xs break-words text-ink-2">
                    {formatValue(line, 240)}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {Object.keys(a.tool_issues).length ? (
        <p className="text-xs text-ink-2">
          Tool issues:{" "}
          {Object.entries(a.tool_issues)
            .map(([tool, counts]) => `${tool} (${Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(", ")})`)
            .join("; ")}
        </p>
      ) : null}
    </CardBody>
  );
}

function GatePanel({ baseline, candidate }: { baseline: string; candidate: string }) {
  const gate = useApi(() => api.benchmarkGate(baseline, candidate), [baseline, candidate]);
  if (gate.error) return <p className="text-xs text-critical">Regression gate: {gate.error}</p>;
  if (!gate.data) return <Loading />;
  const shown = gateDisplay(gate.data.verdict);
  const toneClass = { good: "text-good", critical: "text-critical", warning: "text-warning" }[shown.tone];
  const items = [...gate.data.errors, ...gate.data.regressions];
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium text-ink-2">
        Regression gate (default thresholds: no drop allowed) —{" "}
        <span className={toneClass}>{shown.label}</span>
        <span className="text-muted"> · exit {gate.data.exit_code}</span>
      </h3>
      {items.length === 0 ? (
        <p className="text-xs text-muted">No threshold violated.</p>
      ) : (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-2">
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs text-muted">
        Same rules as <span className="font-mono">agentforge bench gate</span> in CI.
      </p>
    </div>
  );
}

function CycleDetails({ cycle, reload }: { cycle: ImprovementCycle; reload: () => void }) {
  const action = useAction(reload);
  const allowed = cycleActions(cycle);
  const c = cycle.comparison;
  return (
    <div className="space-y-4 border-t border-line bg-page/40 px-4 py-3">
      <div>
        <h3 className="mb-1 text-xs font-medium text-ink-2">
          Proposal ({cycle.proposal.proposer}) from{" "}
          <Link href={`/benchmarks/${cycle.baseline_benchmark_run_id}`} className="underline">
            baseline benchmark
          </Link>
        </h3>
        {cycle.proposal.changes.length === 0 ? (
          <p className="text-[13px] text-muted">No config change applies to these failures.</p>
        ) : (
          <ul className="space-y-2">
            {cycle.proposal.changes.map((change) => (
              <li key={change.id} className="text-[13px]">
                <span className="font-mono text-xs">
                  {change.id} {describeChange(change)}
                </span>
                {cycle.applied_change_ids.includes(change.id) ? (
                  <span className="ml-2 inline-flex items-center gap-0.5 text-xs text-ink-2">
                    <Check aria-hidden className="size-3 text-good" /> applied
                  </span>
                ) : null}
                {change.rationale ? <p className="text-xs text-ink-2">{change.rationale}</p> : null}
                {change.addresses.length ? (
                  <p className="text-xs text-muted">addresses: {change.addresses.map(categoryLabel).join(", ")}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {cycle.proposal.notes.map((note, i) => (
          <p key={i} className="mt-1 text-xs text-muted">
            Note: {note}
          </p>
        ))}
        {cycle.notes ? <p className="mt-1 text-xs text-ink-2">{cycle.notes}</p> : null}
      </div>

      {cycle.status === "evaluated" && cycle.candidate_benchmark_run_id ? (
        <GatePanel baseline={cycle.baseline_benchmark_run_id} candidate={cycle.candidate_benchmark_run_id} />
      ) : null}

      {c ? (
        <div>
          <h3 className="mb-1 text-xs font-medium text-ink-2">
            Comparison v{cycle.from_version} → v{cycle.to_version} ·{" "}
            <Link href={`/benchmarks/${cycle.candidate_benchmark_run_id}`} className="underline">
              candidate benchmark
            </Link>
          </h3>
          {!c.comparable ? (
            <p className="text-[13px] text-ink-2">Not comparable: {c.reasons.join("; ")}</p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {[c.baseline, c.candidate].map((side, i) =>
                  side ? (
                    <div key={i}>
                      <p className="text-xs text-muted">
                        {i === 0 ? "Baseline" : "Candidate"} v{side.agent_version} · {side.passed}/{side.runs}
                      </p>
                      <RateWithInterval rate={side.pass_rate} interval={side.pass_rate_ci95} />
                    </div>
                  ) : null,
                )}
              </div>
              <Table className="mt-2">
                <THead>
                  <TR>
                    <TH>Task</TH>
                    <TH className="text-right">Before</TH>
                    <TH className="text-right">After</TH>
                    <TH>Change</TH>
                  </TR>
                </THead>
                <TBody>
                  {c.tasks.map((t) => (
                    <TR key={t.task_id}>
                      <TD className="font-mono text-xs">{t.task_id}</TD>
                      <TD className="tabular text-right">
                        {t.baseline_passed}/{t.baseline_runs}
                      </TD>
                      <TD className="tabular text-right">
                        {t.candidate_passed}/{t.candidate_runs}
                      </TD>
                      <TD className="text-xs text-ink-2">{t.change}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {c.categories.length ? (
                <p className="mt-2 text-xs text-ink-2">
                  Failure categories:{" "}
                  {c.categories
                    .map((row) => `${categoryLabel(row.category)} ${row.baseline} → ${row.candidate}`)
                    .join(" · ")}
                </p>
              ) : null}
            </>
          )}
          {c.notes.map((note, i) => (
            <p key={i} className="mt-1 text-xs text-muted">
              Note: {note}
            </p>
          ))}
        </div>
      ) : null}
      {cycle.reverted_to_version ? (
        <p className="text-xs text-ink-2">Reverted: the baseline configuration was stored as v{cycle.reverted_to_version}.</p>
      ) : null}
      {cycle.error ? <p className="text-xs text-critical-text">{cycle.error}</p> : null}

      <div className="flex flex-wrap gap-2">
        {allowed.apply ? (
          <Button size="sm" disabled={action.busy} onClick={() => action.run(() => api.applyImprovement(cycle.id))}>
            <Check aria-hidden className="size-3.5" /> Apply as v{cycle.from_version + 1}
          </Button>
        ) : null}
        {allowed.evaluate ? (
          <Button size="sm" disabled={action.busy} onClick={() => action.run(() => api.evaluateImprovement(cycle.id))}>
            <Play aria-hidden className="size-3.5" /> Benchmark v{cycle.to_version} and compare
          </Button>
        ) : null}
        {allowed.reject ? (
          <Button
            size="sm"
            variant="outline"
            disabled={action.busy}
            onClick={() => {
              const revert = cycle.to_version !== null;
              if (revert && !window.confirm("Reject and restore the baseline configuration as a new version?")) return;
              void action.run(() => api.rejectImprovement(cycle.id));
            }}
          >
            <Undo2 aria-hidden className="size-3.5" /> {cycle.to_version ? "Reject and revert" : "Reject"}
          </Button>
        ) : null}
      </div>
      {action.error ? <p className="text-xs text-critical-text">{action.error}</p> : null}
    </div>
  );
}

function VersionRow({ version, parent }: { version: AgentVersion; parent: AgentVersion | undefined }) {
  const diff = parent ? configDiff(parent.config, version.config) : [];
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
        <span>
          <span className="tabular font-medium">v{version.version}</span>{" "}
          <span className="text-ink-2">{version.source}</span>
          {version.improvement_id ? <span className="font-mono text-xs text-muted"> · {version.improvement_id}</span> : null}
        </span>
        <span className="text-xs text-muted">{relativeTime(version.created_at)}</span>
      </div>
      {version.change_summary ? <p className="mt-0.5 text-xs text-ink-2">{version.change_summary}</p> : null}
      {diff.length ? (
        <ul className="mt-1 space-y-0.5">
          {diff.slice(0, 8).map((d) => (
            <li key={d.path} className="font-mono text-xs break-words text-muted">
              {d.path}: {formatValue(d.before, 40)} → {formatValue(d.after, 40)}
            </li>
          ))}
          {diff.length > 8 ? <li className="text-xs text-muted">…and {diff.length - 8} more</li> : null}
        </ul>
      ) : null}
    </li>
  );
}

export default function AgentImprovementPage() {
  const { id } = useParams<{ id: string }>();
  const agent = useApi(() => api.agent(id), [id]);
  const versions = useApi(() => api.agentVersions(id), [id]);
  const benches = useApi(() => api.benchmarkRuns({ agent_id: id, limit: 200 }), [id], {
    pollMs: (data) => (data?.some((b) => !isTerminal(b.status)) ? 3_000 : 20_000),
  });
  const cycles = useApi(() => api.improvements({ agent_id: id }), [id], {
    pollMs: (data) => (data?.some((c) => c.status === "evaluating") ? 3_000 : 20_000),
  });
  const suites = useApi(() => api.suites(), []);
  const [tab, setTab] = useState<ResultClass>("offline");
  const [chosen, setChosen] = useState<string>();
  const [expanded, setExpanded] = useState<string | null>();
  const [suiteId, setSuiteId] = useState("");
  const reloadAll = () => {
    agent.reload();
    versions.reload();
    benches.reload();
    cycles.reload();
  };
  const start = useAction(reloadAll);

  if (agent.error) return <ErrorState message={agent.error} />;
  if (!agent.data) return <Loading />;
  const a = agent.data;
  const split = splitByResultClass(benches.data ?? []);
  const shownClass: ResultClass = split[tab].length === 0 && split.offline.length + split.real.length > 0
    ? split.offline.length ? "offline" : "real"
    : tab;
  const finished = split[shownClass].filter((b) => isTerminal(b.status) && b.summary);
  // Default: the most recent finished run with failures (else the most recent finished run).
  const selected =
    chosen ?? (finished.find((b) => b.summary && b.summary.passed < b.summary.runs) ?? finished[0])?.id;
  const selectedBench = (benches.data ?? []).find((b) => b.id === selected);
  const open = expanded === undefined ? cycles.data?.[0]?.id : expanded;
  const versionList = versions.data ?? [];

  return (
    <>
      <PageHeader
        title={`${a.name} · improvement`}
        description={
          <span className="flex flex-wrap items-center gap-x-3">
            <span className="font-mono text-xs">
              {a.config.model.provider}/{a.config.model.model || "-"}
            </span>
            <span>current v{a.version}</span>
            <ResultClassBadge value={a.config.model.provider === "scripted" ? "offline" : "real"} />
            <Link href={`/agents/${a.id}`} className="hover:underline">
              agent details
            </Link>
          </span>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Versions" value={versionList.length || "—"} />
        <StatTile
          label="Benchmark runs"
          value={(benches.data ?? []).length}
          hint={`${split.offline.length} offline · ${split.real.length} real`}
        />
        <StatTile label="Improvement cycles" value={(cycles.data ?? []).length} />
        <StatTile
          label="Last comparison"
          value={<VerdictBadge verdict={cycles.data?.find((c) => c.comparison)?.comparison?.verdict} />}
          hint={formatDelta(cycles.data?.find((c) => c.comparison)?.comparison?.pass_rate_delta)}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="min-w-0 space-y-5 xl:col-span-2">
          <Card>
            <CardHeader
              title="Benchmark runs"
              description="Offline (scripted) and real-model results are listed separately and never compared."
              action={
                <div className="flex gap-1" role="tablist" aria-label="Result class">
                  {(["offline", "real"] as const).map((cls) => (
                    <Button
                      key={cls}
                      size="sm"
                      role="tab"
                      aria-selected={shownClass === cls}
                      variant={shownClass === cls ? "outline" : "ghost"}
                      onClick={() => {
                        setTab(cls);
                        setChosen(undefined);
                      }}
                    >
                      {cls === "offline" ? "Offline" : "Real model"} ({split[cls].length})
                    </Button>
                  ))}
                </div>
              }
            />
            {!benches.data ? (
              <Loading />
            ) : (
              <BenchmarkTable runs={split[shownClass]} selected={selected} onSelect={setChosen} />
            )}
            <div className="flex flex-wrap items-end gap-2 border-t border-line px-4 py-3">
              <div className="min-w-48 flex-1">
                <Label htmlFor="suite">Benchmark the current version (v{a.version})</Label>
                <Select id="suite" value={suiteId} onChange={(e) => setSuiteId(e.target.value)}>
                  <option value="">Choose a suite…</option>
                  {(suites.data ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.id}@{s.version})
                    </option>
                  ))}
                </Select>
              </div>
              <Button
                disabled={!suiteId || start.busy}
                onClick={() => start.run(() => api.startBenchmark({ suite_id: suiteId, agent_id: a.id }))}
              >
                <FlaskConical aria-hidden className="size-3.5" /> Run benchmark
              </Button>
              {start.error ? <p className="w-full text-xs text-critical-text">{start.error}</p> : null}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Failure analysis"
              description={
                selectedBench
                  ? `Benchmark ${selectedBench.id} (${resultClassOf(selectedBench)})`
                  : "Choose “Analyse” on a finished benchmark run."
              }
            />
            {selectedBench ? (
              <AnalysisPanel
                benchId={selectedBench.id}
                canPropose={Boolean(selectedBench.agent_version)}
                onProposed={reloadAll}
              />
            ) : (
              <Empty>No benchmark selected.</Empty>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Improvement history"
              description="Analysis → proposal → new version → re-benchmark → comparison. Click a cycle for details."
            />
            {!cycles.data ? (
              <Loading />
            ) : cycles.data.length === 0 ? (
              <Empty>No cycles yet. Analyse a benchmark run and propose an improvement.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {cycles.data.map((cycle) => (
                  <li key={cycle.id}>
                    <button
                      type="button"
                      className="grid w-full grid-cols-2 items-center gap-2 px-4 py-2.5 text-left text-[13px] hover:bg-surface-2 md:grid-cols-[7rem_7rem_1fr_8rem_8rem_5rem]"
                      aria-expanded={open === cycle.id}
                      onClick={() => setExpanded(open === cycle.id ? null : cycle.id)}
                    >
                      <span className="text-xs text-ink-2">{relativeTime(cycle.created_at)}</span>
                      <span className="tabular">
                        v{cycle.from_version} → {cycle.to_version ? `v${cycle.to_version}` : "—"}
                      </span>
                      <span className="truncate text-xs text-ink-2">
                        {cycle.proposal.changes.length} change(s) ·{" "}
                        {Object.keys(cycle.analysis.categories).map(categoryLabel).join(", ") || "no failures"}
                      </span>
                      <CycleStatusBadge status={cycle.status} />
                      <VerdictBadge verdict={cycle.comparison?.verdict} />
                      <span className="tabular text-right text-xs">
                        {formatDelta(cycle.comparison?.pass_rate_delta)}
                      </span>
                    </button>
                    {open === cycle.id ? <CycleDetails cycle={cycle} reload={reloadAll} /> : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card className="min-w-0 self-start">
          <CardHeader title="Agent versions" description="Immutable config snapshots, newest first." />
          {!versions.data ? (
            <Loading />
          ) : (
            <ul className="divide-y divide-line">
              {versionList.map((v) => (
                <VersionRow
                  key={v.version}
                  version={v}
                  parent={versionList.find((p) => p.version === (v.parent_version ?? v.version - 1))}
                />
              ))}
            </ul>
          )}
          <p className="border-t border-line px-4 py-2 text-xs text-muted">
            Pass rates are comparable only within one suite version and result class. Offline pass rates
            say nothing about a model.
          </p>
        </Card>
      </div>
    </>
  );
}
