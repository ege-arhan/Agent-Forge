"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { InlineBar, RateWithInterval } from "@/components/bars";
import { PageHeader } from "@/components/page-header";
import { RunStatusBadge } from "@/components/status";
import { ErrorState, Loading } from "@/components/states";
import { Pre } from "@/components/trace";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import {
  formatCost,
  formatDelta,
  formatDuration,
  formatNumber,
  formatPercent,
  isTerminal,
  relativeTime,
} from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function ExperimentPage() {
  const { id } = useParams<{ id: string }>();
  const data = useApi(() => api.experiment(id), [id], {
    pollMs: (d) => (d && !isTerminal(d.experiment.status) ? 3_000 : undefined),
  });
  if (data.error) return <ErrorState message={data.error} />;
  if (!data.data) return <Loading />;
  const { experiment: e, comparison } = data.data;
  const taskIds = Array.from(new Set(comparison.flatMap((row) => Object.keys(row.task_pass_rates))));

  return (
    <>
      <PageHeader
        title={e.name}
        description={
          <span className="flex flex-wrap items-center gap-x-3">
            <RunStatusBadge status={e.status} />
            <span className="font-mono text-xs">{e.suite_id}</span>
            <span>{relativeTime(e.created_at)}</span>
            {e.description ? <span>{e.description}</span> : null}
          </span>
        }
      />

      <Card>
        <CardHeader
          title="Comparison"
          description="First variant is the baseline. Overlapping intervals mean the data does not separate the variants."
        />
        <Table>
          <THead>
            <TR>
              <TH>Variant</TH>
              <TH>Model</TH>
              <TH className="text-right">Runs</TH>
              <TH>Pass rate (95% CI)</TH>
              <TH className="text-right">Δ vs baseline</TH>
              <TH className="text-right">Mean score</TH>
              <TH className="text-right">Mean steps</TH>
              <TH className="text-right">Mean duration</TH>
              <TH className="text-right">Cost</TH>
            </TR>
          </THead>
          <TBody>
            {e.variants.map((v) => {
              const row = comparison.find((c) => c.variant === v.variant);
              return (
                <TR key={v.variant}>
                  <TD>
                    <Link href={`/benchmarks/${v.benchmark_run_id}`} className="font-medium hover:underline">
                      {v.variant}
                    </Link>
                    {!row ? (
                      <div className="mt-0.5">
                        <RunStatusBadge status={v.status} />
                      </div>
                    ) : null}
                  </TD>
                  <TD className="font-mono text-xs text-ink-2">
                    {v.provider}/{v.model || "-"}
                  </TD>
                  <TD className="tabular text-right">{row?.runs ?? "—"}</TD>
                  <TD className="w-72">
                    {row ? (
                      <>
                        <RateWithInterval rate={row.pass_rate} interval={row.pass_rate_ci95} />
                        {row.pass_rate_ci95 ? (
                          <div className="tabular text-xs text-muted">
                            {formatPercent(row.pass_rate_ci95[0])}–{formatPercent(row.pass_rate_ci95[1])}
                          </div>
                        ) : null}
                      </>
                    ) : (
                      "—"
                    )}
                  </TD>
                  <TD className="tabular text-right">{row ? formatDelta(row.pass_rate_delta) : "—"}</TD>
                  <TD className="tabular text-right">{row ? formatNumber(row.mean_score) : "—"}</TD>
                  <TD className="tabular text-right">{row ? formatNumber(row.mean_steps) : "—"}</TD>
                  <TD className="tabular text-right">{row ? formatDuration(row.mean_duration_seconds) : "—"}</TD>
                  <TD className="tabular text-right">{row ? formatCost(row.total_cost_usd) : "—"}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </Card>

      {taskIds.length > 0 ? (
        <Card className="mt-5">
          <CardHeader title="Pass rate by task" description="Rows are tasks; columns are variants." />
          <Table>
            <THead>
              <TR>
                <TH>Task</TH>
                {comparison.map((row) => (
                  <TH key={row.variant}>{row.variant}</TH>
                ))}
              </TR>
            </THead>
            <TBody>
              {taskIds.map((task) => (
                <TR key={task}>
                  <TD className="font-mono text-xs">{task}</TD>
                  {comparison.map((row) => (
                    <TD key={row.variant}>
                      <InlineBar value={row.task_pass_rates[task]} />
                    </TD>
                  ))}
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      ) : null}

      <Card className="mt-5">
        <CardHeader title="Variant overrides" />
        <CardBody>
          <Pre>{JSON.stringify(e.spec.variants, null, 2)}</Pre>
          <p className="mt-2 text-xs text-muted">
            Results describe these configurations on this suite with the stated number of runs. They are not general
            model rankings.
          </p>
        </CardBody>
      </Card>
    </>
  );
}
