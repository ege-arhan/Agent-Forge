"use client";

import { useState } from "react";

import { DailyChart } from "@/components/daily-chart";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatCost, formatDuration, formatTokens } from "@/lib/format";
import { durationUnit, formatDay, rangeTotals } from "@/lib/timeseries";
import { useApi } from "@/lib/use-api";

const RANGES = [7, 14, 30, 90] as const;

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** Runs, tokens, known cost and mean duration per UTC day, as four small charts. */
export function Activity() {
  const [days, setDays] = useState<number>(14);
  const series = useApi(() => api.timeseries(days), [days], { pollMs: 30_000 });
  const points = series.data?.series ?? [];
  const totals = rangeTotals(points);
  const count = (value: number | null) => (value === null ? "—" : String(value));
  const axis = durationUnit(Math.max(0, ...points.map((d) => d.mean_duration_seconds ?? 0)));

  return (
    <Card className="mt-5">
      <CardHeader
        title="Activity over time"
        description="Per day (UTC). Tokens, cost and duration count finished runs."
        action={
          <div className="flex gap-1" role="group" aria-label="Time range">
            {RANGES.map((range) => (
              <button
                key={range}
                type="button"
                aria-pressed={days === range}
                onClick={() => setDays(range)}
                className={`h-7 rounded-md px-2 text-xs font-medium ${
                  days === range
                    ? "bg-surface-2 text-ink"
                    : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                }`}
              >
                {range}d
              </button>
            ))}
          </div>
        }
      />
      {series.error ? (
        <div className="p-4">
          <ErrorState message={series.error} />
        </div>
      ) : !series.data ? (
        <Loading />
      ) : totals.runs === 0 ? (
        <Empty>No runs in the last {days} days.</Empty>
      ) : (
        <>
          <div className="grid gap-x-8 gap-y-6 p-4 md:grid-cols-2 2xl:grid-cols-4">
            <DailyChart
              title="Runs"
              summary={`${plural(totals.runs, "run")} · ${totals.succeeded} succeeded · ${totals.failed} failed`}
              integer
              format={count}
              points={points.map((d) => ({
                date: d.date,
                value: d.runs,
                detail: d.runs ? [`${d.succeeded} succeeded · ${d.failed} failed`] : [],
              }))}
            />
            <DailyChart
              title="Tokens"
              summary={`${formatTokens(totals.tokens)} in and out`}
              integer
              format={formatTokens}
              points={points.map((d) => ({
                date: d.date,
                value: d.input_tokens + d.output_tokens,
                detail: [`${formatTokens(d.input_tokens)} in · ${formatTokens(d.output_tokens)} out`],
              }))}
            />
            <DailyChart
              title="Known cost"
              summary={
                `${formatCost(totals.knownCostUsd)}` +
                (totals.runsWithUnknownCost
                  ? ` · ${plural(totals.runsWithUnknownCost, "run")} with unknown pricing not included`
                  : "")
              }
              format={formatCost}
              points={points.map((d) => ({
                date: d.date,
                value: d.known_cost_usd,
                detail: d.runs_with_unknown_cost
                  ? [`+ ${plural(d.runs_with_unknown_cost, "run")} with unknown pricing`]
                  : [],
              }))}
            />
            <DailyChart
              title="Mean run duration"
              summary={`${formatDuration(totals.meanDurationSeconds)} per run`}
              format={formatDuration}
              unit={{ per: axis.seconds, suffix: axis.suffix }}
              points={points.map((d) => ({
                date: d.date,
                value: d.mean_duration_seconds,
                detail: d.timed_runs ? [`over ${plural(d.timed_runs, "run")}`] : [],
              }))}
            />
          </div>
          <details className="border-t border-line">
            <summary className="cursor-pointer px-4 py-2 text-xs text-ink-2 hover:text-ink">
              Show as table
            </summary>
            <div className="max-h-80 overflow-auto">
              <Table>
                <THead>
                  <TR>
                    <TH>Day</TH>
                    <TH className="text-right">Runs</TH>
                    <TH className="text-right">Succeeded</TH>
                    <TH className="text-right">Failed</TH>
                    <TH className="text-right">Tokens in</TH>
                    <TH className="text-right">Tokens out</TH>
                    <TH className="text-right">Known cost</TH>
                    <TH className="text-right">Unknown pricing</TH>
                    <TH className="text-right">Mean duration</TH>
                  </TR>
                </THead>
                <TBody>
                  {[...points].reverse().map((d) => (
                    <TR key={d.date}>
                      <TD className="whitespace-nowrap">{formatDay(d.date)}</TD>
                      <TD className="tabular text-right">{d.runs}</TD>
                      <TD className="tabular text-right">{d.succeeded}</TD>
                      <TD className="tabular text-right">{d.failed}</TD>
                      <TD className="tabular text-right">{formatTokens(d.input_tokens)}</TD>
                      <TD className="tabular text-right">{formatTokens(d.output_tokens)}</TD>
                      <TD className="tabular text-right">
                        {d.runs ? formatCost(d.known_cost_usd) : "—"}
                      </TD>
                      <TD className="tabular text-right">{d.runs_with_unknown_cost}</TD>
                      <TD className="tabular text-right">{formatDuration(d.mean_duration_seconds)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          </details>
        </>
      )}
    </Card>
  );
}
