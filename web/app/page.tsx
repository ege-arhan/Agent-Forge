"use client";

import Link from "next/link";

import { InlineBar } from "@/components/bars";
import { PageHeader } from "@/components/page-header";
import { RunsTable } from "@/components/runs-table";
import { Empty, ErrorState, Loading } from "@/components/states";
import { StatTile } from "@/components/stat-tile";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatCost, formatNumber, formatPercent, formatTokens, relativeTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function DashboardPage() {
  const stats = useApi(() => api.stats(), [], {
    pollMs: (data) => (data && data.active_runs > 0 ? 3_000 : 15_000),
  });
  const runs = useApi(() => api.runs({ limit: 10 }), [], {
    pollMs: () => (stats.data && stats.data.active_runs > 0 ? 3_000 : 15_000),
  });
  const benches = useApi(() => api.benchmarkRuns({ limit: 5 }), [], { pollMs: 15_000 });

  if (stats.error) return <ErrorState message={stats.error} />;
  const s = stats.data;

  const tools = Object.entries(s?.tool_calls ?? {})
    .map(([tool, counts]) => {
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      const ok = counts.success ?? 0;
      return { tool, total, ok, errors: total - ok, rate: total ? ok / total : null };
    })
    .sort((a, b) => b.total - a.total);

  return (
    <>
      <PageHeader title="Dashboard" description="Execution, evaluation and cost across all runs." />

      {!s ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile label="Runs" value={s.total_runs} hint={`${s.runs_by_status.failed ?? 0} failed`} />
          <StatTile label="Active runs" value={s.active_runs} hint="running or pending" />
          <StatTile
            label="Evaluation pass rate"
            value={formatPercent(s.evaluation_pass_rate)}
            hint={`${s.evaluated_runs} evaluated · mean score ${formatNumber(s.mean_evaluation_score)}`}
          />
          <StatTile
            label="Completion rate"
            value={formatPercent(s.completion_rate)}
            hint="final answer produced"
          />
          <StatTile
            label="Known cost"
            value={formatCost(s.known_cost_usd)}
            hint={
              s.runs_with_unknown_cost
                ? `+ ${s.runs_with_unknown_cost} run(s) with unknown pricing`
                : `${formatTokens(s.input_tokens)} in / ${formatTokens(s.output_tokens)} out tokens`
            }
          />
        </div>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          <CardHeader
            title="Recent runs"
            action={
              <Link href="/runs" className="text-xs text-ink-2 hover:text-ink">
                All runs →
              </Link>
            }
          />
          {runs.error ? (
            <div className="p-4">
              <ErrorState message={runs.error} />
            </div>
          ) : !runs.data ? (
            <Loading />
          ) : (
            <RunsTable runs={runs.data.items} compact />
          )}
        </Card>

        <Card>
          <CardHeader title="Tool reliability" description="Share of tool calls that succeeded." />
          {tools.length === 0 ? (
            <Empty>No tool calls yet.</Empty>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Tool</TH>
                  <TH className="text-right">Calls</TH>
                  <TH>Success</TH>
                </TR>
              </THead>
              <TBody>
                {tools.map((t) => (
                  <TR key={t.tool}>
                    <TD className="font-mono text-xs">{t.tool}</TD>
                    <TD className="tabular text-right">{t.total}</TD>
                    <TD>
                      <InlineBar value={t.rate} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title="Recent benchmark runs"
          action={
            <Link href="/benchmarks" className="text-xs text-ink-2 hover:text-ink">
              Benchmarks →
            </Link>
          }
        />
        {!benches.data ? (
          <Loading />
        ) : benches.data.length === 0 ? (
          <Empty>No benchmark runs yet.</Empty>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Suite</TH>
                <TH>Agent</TH>
                <TH>Variant</TH>
                <TH className="text-right">Runs</TH>
                <TH>Pass rate</TH>
                <TH>When</TH>
              </TR>
            </THead>
            <TBody>
              {benches.data.map((b) => (
                <TR key={b.id}>
                  <TD>
                    <Link href={`/benchmarks/${b.id}`} className="hover:underline">
                      {b.suite_name}
                    </Link>
                  </TD>
                  <TD>{b.agent_name}</TD>
                  <TD className="text-ink-2">{b.variant ?? "—"}</TD>
                  <TD className="tabular text-right">{b.summary?.runs ?? b.results.length}</TD>
                  <TD>
                    <InlineBar value={b.summary?.pass_rate} />
                  </TD>
                  <TD className="text-ink-2">{relativeTime(b.created_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
