"use client";

import Link from "next/link";

import { RateWithInterval } from "@/components/bars";
import { CycleStatusBadge, VerdictBadge } from "@/components/improvement";
import { PageHeader } from "@/components/page-header";
import { RunStatusBadge } from "@/components/status";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatDelta, relativeTime } from "@/lib/format";
import { resultClassOf } from "@/lib/improvement";
import type { BenchmarkRun, ResultClass } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const STEPS = [
  "Agent version",
  "Benchmark",
  "Evaluation",
  "Failure analysis",
  "Improvement proposal",
  "New version",
  "Benchmark again",
  "Compare",
];

function latest(benches: BenchmarkRun[], agentId: string, cls: ResultClass): BenchmarkRun | undefined {
  return benches.find((b) => b.agent_id === agentId && resultClassOf(b) === cls && b.summary);
}

function LatestRate({ bench }: { bench: BenchmarkRun | undefined }) {
  if (!bench?.summary) return <span className="text-[13px] text-muted">—</span>;
  return (
    <div>
      <RateWithInterval rate={bench.summary.pass_rate} interval={bench.summary.pass_rate_ci95} />
      <div className="mt-0.5 text-xs text-muted">
        v{bench.agent_version ?? "?"} · {bench.suite_id}
      </div>
    </div>
  );
}

export default function ImprovementPage() {
  const agents = useApi(() => api.agents(), []);
  const benches = useApi(() => api.benchmarkRuns({ limit: 500 }), [], { pollMs: 15_000 });
  const cycles = useApi(() => api.improvements({ limit: 200 }), [], { pollMs: 15_000 });
  const experiments = useApi(() => api.experiments(), []);

  if (agents.error) return <ErrorState message={agents.error} />;

  return (
    <>
      <PageHeader
        title="Improvement"
        description="Systematically improve agents: every version, benchmark, analysis, proposal and comparison is kept."
      />
      <Card className="mb-5">
        <CardBody>
          <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-2">
            {STEPS.map((step, i) => (
              <li key={step} className="flex items-center gap-2">
                <span className="rounded-md border border-line px-2 py-0.5">{step}</span>
                {i < STEPS.length - 1 ? <span aria-hidden>→</span> : null}
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-muted">
            Offline results (scripted provider) validate the pipeline and the benchmark only; they are shown
            and compared separately from real-model results and never mixed.
          </p>
        </CardBody>
      </Card>

      <Card className="mb-5">
        <CardHeader title="Agents" description="Latest benchmark per result class and improvement cycles." />
        {!agents.data || !benches.data || !cycles.data ? (
          <Loading />
        ) : agents.data.length === 0 ? (
          <Empty>
            No stored agents yet. Create one on the <Link href="/agents" className="underline">Agents</Link> page or
            run <code className="font-mono">scripts/dogfood.py offline</code>.
          </Empty>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Agent</TH>
                <TH>Version</TH>
                <TH>Latest offline</TH>
                <TH>Latest real model</TH>
                <TH className="text-right">Cycles</TH>
                <TH>Last verdict</TH>
              </TR>
            </THead>
            <TBody>
              {agents.data.map((agent) => {
                const own = cycles.data!.filter((c) => c.agent_id === agent.id);
                const last = own.find((c) => c.comparison);
                return (
                  <TR key={agent.id}>
                    <TD>
                      <Link href={`/improvement/${agent.id}`} className="font-medium hover:underline">
                        {agent.name}
                      </Link>
                      <div className="font-mono text-xs text-muted">
                        {agent.config.model.provider}/{agent.config.model.model || "-"}
                      </div>
                    </TD>
                    <TD className="tabular">v{agent.version}</TD>
                    <TD>
                      <LatestRate bench={latest(benches.data!, agent.id, "offline")} />
                    </TD>
                    <TD>
                      <LatestRate bench={latest(benches.data!, agent.id, "real")} />
                    </TD>
                    <TD className="tabular text-right">{own.length}</TD>
                    <TD>
                      <VerdictBadge verdict={last?.comparison?.verdict} />
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader title="Improvement history" description="Most recent cycles across all agents." />
          {!cycles.data ? (
            <Loading />
          ) : cycles.data.length === 0 ? (
            <Empty>No improvement cycles yet.</Empty>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Agent</TH>
                  <TH>Versions</TH>
                  <TH>Status</TH>
                  <TH>Verdict</TH>
                  <TH className="text-right whitespace-nowrap">Δ pass rate</TH>
                </TR>
              </THead>
              <TBody>
                {cycles.data.slice(0, 20).map((c) => (
                  <TR key={c.id}>
                    <TD className="text-xs whitespace-nowrap text-ink-2">{relativeTime(c.created_at)}</TD>
                    <TD>
                      <Link href={`/improvement/${c.agent_id}`} className="whitespace-nowrap hover:underline">
                        {c.agent_name}
                      </Link>
                      <div className="text-xs text-muted">{c.result_class === "offline" ? "offline" : "real model"}</div>
                    </TD>
                    <TD className="tabular whitespace-nowrap">
                      v{c.from_version} → {c.to_version ? `v${c.to_version}` : "—"}
                    </TD>
                    <TD>
                      <CycleStatusBadge status={c.status} />
                    </TD>
                    <TD>
                      <VerdictBadge verdict={c.comparison?.verdict} />
                    </TD>
                    <TD className="tabular text-right whitespace-nowrap">{formatDelta(c.comparison?.pass_rate_delta)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>

        <Card className="min-w-0">
          <CardHeader title="Experiment history" description="Variant comparisons on a benchmark suite." />
          {!experiments.data ? (
            <Loading />
          ) : experiments.data.length === 0 ? (
            <Empty>No experiments yet.</Empty>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Experiment</TH>
                  <TH>Suite</TH>
                  <TH className="text-right">Variants</TH>
                  <TH>Status</TH>
                  <TH>When</TH>
                </TR>
              </THead>
              <TBody>
                {experiments.data.slice(0, 20).map((e) => (
                  <TR key={e.id}>
                    <TD>
                      <Link href={`/experiments/${e.id}`} className="hover:underline">
                        {e.name}
                      </Link>
                    </TD>
                    <TD className="font-mono text-xs">{e.suite_id}</TD>
                    <TD className="tabular text-right">{e.variants.length}</TD>
                    <TD>
                      <RunStatusBadge status={e.status} />
                    </TD>
                    <TD className="text-xs text-ink-2">{relativeTime(e.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
