"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { InlineBar, RateWithInterval } from "@/components/bars";
import { PageHeader } from "@/components/page-header";
import { ErrorState, Loading } from "@/components/states";
import { StatTile } from "@/components/stat-tile";
import { EvalBadge, RunStatusBadge } from "@/components/status";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import {
  formatCost,
  formatDuration,
  formatNumber,
  formatPercent,
  formatTokens,
  isTerminal,
  relativeTime,
} from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function BenchmarkRunPage() {
  const { id } = useParams<{ id: string }>();
  const bench = useApi(() => api.benchmarkRun(id), [id], {
    pollMs: (data) => (data && !isTerminal(data.status) ? 2_000 : undefined),
  });
  if (bench.error) return <ErrorState message={bench.error} />;
  if (!bench.data) return <Loading />;
  const b = bench.data;
  const s = b.summary;

  return (
    <>
      <PageHeader
        title={`${b.suite_name} · ${b.agent_name}`}
        description={
          <span className="flex flex-wrap items-center gap-x-3">
            <RunStatusBadge status={b.status} />
            <span className="font-mono text-xs">
              {b.agent_config.model.provider}/{b.agent_config.model.model || "-"}
            </span>
            {b.variant ? <span>variant {b.variant}</span> : null}
            {b.experiment_id ? (
              <Link href={`/experiments/${b.experiment_id}`} className="hover:underline">
                experiment
              </Link>
            ) : null}
            <span>{relativeTime(b.created_at)}</span>
          </span>
        }
      />

      {s ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <StatTile
            label="Pass rate"
            value={formatPercent(s.pass_rate)}
            hint={s.pass_rate_ci95 ? `95% CI ${formatPercent(s.pass_rate_ci95[0])}–${formatPercent(s.pass_rate_ci95[1])}` : undefined}
          />
          <StatTile label="Runs" value={s.runs} hint={`${s.passed} passed · ${s.errors} not succeeded`} />
          <StatTile
            label="Mean score"
            value={formatNumber(s.mean_score)}
            hint={s.score_stddev !== null ? `sd ${formatNumber(s.score_stddev)}` : undefined}
          />
          <StatTile label="Mean duration" value={formatDuration(s.mean_duration_seconds)} />
          <StatTile
            label="Tokens"
            value={formatTokens(s.total_input_tokens + s.total_output_tokens)}
            hint={`mean steps ${formatNumber(s.mean_steps)}`}
          />
          <StatTile label="Total cost" value={formatCost(s.total_cost_usd)} />
        </div>
      ) : (
        <p className="text-[13px] text-ink-2">
          Running… {b.results.length} result(s) so far ({b.repeats} repeat(s) per task).
        </p>
      )}

      {s && s.tasks.length > 0 ? (
        <Card className="mt-5">
          <CardHeader title="Per-task pass rate" description="Share of repeats whose evaluation passed." />
          <Table>
            <THead>
              <TR>
                <TH>Task</TH>
                <TH className="text-right">Runs</TH>
                <TH>Pass rate</TH>
                <TH className="text-right">Mean score</TH>
                <TH className="text-right">Score sd</TH>
                <TH className="text-right">Mean steps</TH>
                <TH className="text-right">Mean duration</TH>
              </TR>
            </THead>
            <TBody>
              {s.tasks.map((t) => (
                <TR key={t.task_id}>
                  <TD className="font-mono text-xs">{t.task_id}</TD>
                  <TD className="tabular text-right">{t.runs}</TD>
                  <TD className="w-64">
                    <InlineBar value={t.pass_rate} />
                  </TD>
                  <TD className="tabular text-right">{formatNumber(t.mean_score)}</TD>
                  <TD className="tabular text-right">{formatNumber(t.score_stddev)}</TD>
                  <TD className="tabular text-right">{formatNumber(t.mean_steps)}</TD>
                  <TD className="tabular text-right">{formatDuration(t.mean_duration_seconds)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <CardBody className="border-t border-line">
            <div className="max-w-md">
              <div className="mb-1 text-xs text-muted">Overall pass rate with 95% Wilson interval</div>
              <RateWithInterval rate={s.pass_rate} interval={s.pass_rate_ci95} />
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Card className="mt-5">
        <CardHeader title="Results" description="Each result is a fully recorded run." />
        <Table>
          <THead>
            <TR>
              <TH>Task</TH>
              <TH className="text-right">Repeat</TH>
              <TH>Status</TH>
              <TH>Evaluation</TH>
              <TH className="text-right">Score</TH>
              <TH className="text-right">Steps</TH>
              <TH className="text-right">Tools ok</TH>
              <TH className="text-right">Duration</TH>
              <TH>Error</TH>
            </TR>
          </THead>
          <TBody>
            {b.results.map((r) => (
              <TR key={`${r.task_id}-${r.repeat}`} className="hover:bg-surface-2">
                <TD className="font-mono text-xs">
                  <Link href={`/runs/${r.run_id}`} className="hover:underline">
                    {r.task_id}
                  </Link>
                </TD>
                <TD className="tabular text-right">{r.repeat}</TD>
                <TD>
                  <RunStatusBadge status={r.status} />
                </TD>
                <TD>
                  <EvalBadge passed={r.passed} />
                </TD>
                <TD className="tabular text-right">{formatNumber(r.score)}</TD>
                <TD className="tabular text-right">{r.steps}</TD>
                <TD className="tabular text-right">{formatPercent(r.tool_success_rate)}</TD>
                <TD className="tabular text-right">{formatDuration(r.duration_seconds)}</TD>
                <TD className="max-w-xs truncate text-xs text-critical-text">{r.error ?? ""}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>

      <Card className="mt-5">
        <CardHeader title="Environment" description="Recorded for reproducibility." />
        <CardBody>
          <dl className="grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2">
            {Object.entries(b.environment).map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="w-36 text-muted">{k}</dt>
                <dd className="font-mono text-xs text-ink">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </CardBody>
      </Card>
    </>
  );
}
