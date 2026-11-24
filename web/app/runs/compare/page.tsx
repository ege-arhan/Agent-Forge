"use client";

import { ArrowLeftRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { Empty, ErrorState, Loading } from "@/components/states";
import { EvalBadge, RunStatusBadge, ToolStatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import {
  alignSteps,
  checkRows,
  compareHref,
  comparisonCaveats,
  configDiff,
  firstDivergence,
  formatMetricDelta,
  type MetricRow,
  metricRows,
  RELATION_LABELS,
  type StepDigest,
} from "@/lib/compare";
import {
  formatCost,
  formatDuration,
  formatNumber,
  formatPercent,
  formatTokens,
  isTerminal,
  relativeTime,
  truncate,
} from "@/lib/format";
import type { Run } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

function metricValue(row: MetricRow, value: number | null): string {
  switch (row.kind) {
    case "duration":
      return formatDuration(value);
    case "percent":
      return formatPercent(value);
    case "tokens":
      return formatTokens(value);
    case "cost":
      return formatCost(value);
    default:
      return formatNumber(value);
  }
}

function RunCard({ side, run }: { side: "A" | "B"; run: Run }) {
  return (
    <Card className="min-w-0">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <span className="rounded border border-line px-1.5 font-mono text-[11px] text-ink-2">{side}</span>
            <Link href={`/runs/${run.id}`} className="truncate hover:underline">
              {truncate(run.goal.split("\n")[0] ?? run.goal, 90)}
            </Link>
          </span>
        }
        action={<RunStatusBadge status={run.status} />}
      />
      <CardBody className="space-y-1 text-[13px] text-ink-2">
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          <span>{run.agent_name}</span>
          <span className="font-mono text-xs">
            {run.config.model.provider}/{run.config.model.model || "-"}
          </span>
          <span>{relativeTime(run.created_at)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <EvalBadge passed={run.evaluation?.passed} />
          {run.error ? <span className="font-mono text-xs text-critical-text">{run.error.type}</span> : null}
          <span className="font-mono text-xs text-muted">{run.id}</span>
        </div>
      </CardBody>
    </Card>
  );
}

function StepCell({ step }: { step: StepDigest | null }) {
  if (!step) return <span className="text-muted">—</span>;
  const kind = step.kind === "plan" ? "Plan" : step.kind === "evaluation" ? "Evaluation" : "Step";
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex flex-wrap items-center gap-x-2 text-xs text-ink-2">
        <span className="font-medium text-ink">
          {kind} {step.index}
        </span>
        {step.passed !== null ? <EvalBadge passed={step.passed} /> : null}
        {step.error ? <span className="font-mono text-critical-text">{step.error}</span> : null}
      </div>
      {step.calls.length === 0 && step.kind === "action" ? (
        <div className="text-xs text-muted">no tool calls</div>
      ) : null}
      {step.calls.map((call, i) => (
        <div key={i} className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 font-mono text-xs font-medium text-ink">{call.tool}</span>
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted" title={call.args}>
            {call.args}
          </span>
          <ToolStatusBadge status={call.status} />
        </div>
      ))}
    </div>
  );
}

function Answer({ run }: { run: Run }) {
  return run.result ? (
    <p className="text-[13px] whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">{run.result}</p>
  ) : (
    <p className="text-[13px] text-muted">{isTerminal(run.status) ? "No final answer." : "Running…"}</p>
  );
}

function Comparison({ a, b }: { a: Run; b: Run }) {
  const metrics = metricRows(a, b);
  const checks = checkRows(a.evaluation, b.evaluation);
  const config = configDiff(a.config, b.config);
  const pairs = alignSteps(a, b);
  const divergence = firstDivergence(pairs);
  const caveats = comparisonCaveats(a, b);

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2">
        <RunCard side="A" run={a} />
        <RunCard side="B" run={b} />
      </div>

      <div className="rounded-md border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">
        <p>
          One run on each side: a difference here is what happened in these two runs, not a measured effect. For
          rates with confidence intervals use a <Link href="/benchmarks" className="underline">benchmark</Link>{" "}
          or an <Link href="/experiments" className="underline">experiment</Link>.
        </p>
        {caveats.length > 0 ? (
          <ul className="mt-1.5 list-disc pl-5 text-ink">
            {caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader title="Metrics" description="Δ is B − A. Unknown values are never treated as zero." />
          <Table>
            <THead>
              <TR>
                <TH>Metric</TH>
                <TH className="text-right">A</TH>
                <TH className="text-right">B</TH>
                <TH className="text-right">Δ</TH>
              </TR>
            </THead>
            <TBody>
              {metrics.map((row) => (
                <TR key={row.key}>
                  <TD className="text-ink-2">{row.label}</TD>
                  <TD className="tabular text-right">{metricValue(row, row.a)}</TD>
                  <TD className="tabular text-right">{metricValue(row, row.b)}</TD>
                  <TD className={cn("tabular text-right", row.delta ? "text-ink" : "text-muted")}>
                    {formatMetricDelta(row)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>

        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title="Evaluation checks" description="Evaluator results by name." />
            {checks.length === 0 ? (
              <Empty>Neither run has evaluator results.</Empty>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Check</TH>
                    <TH>A</TH>
                    <TH>B</TH>
                    <TH />
                  </TR>
                </THead>
                <TBody>
                  {checks.map((row) => (
                    <TR key={row.name}>
                      <TD className="font-mono text-xs">{row.name}</TD>
                      <TD>{row.a === null ? <span className="text-muted">not run</span> : <EvalBadge passed={row.a} />}</TD>
                      <TD>{row.b === null ? <span className="text-muted">not run</span> : <EvalBadge passed={row.b} />}</TD>
                      <TD className="text-xs text-ink-2">{row.changed ? "changed" : ""}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Configuration differences"
              description="Settings that differ between the two configuration snapshots."
            />
            {config.length === 0 ? (
              <Empty>The two runs used the same configuration.</Empty>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Setting</TH>
                    <TH>A</TH>
                    <TH>B</TH>
                  </TR>
                </THead>
                <TBody>
                  {config.map((row) => (
                    <TR key={row.path}>
                      <TD className="font-mono text-xs whitespace-nowrap">{row.path}</TD>
                      {[row.a, row.b].map((value, i) => (
                        <TD key={i} className="max-w-xs font-mono text-xs [overflow-wrap:anywhere]">
                          {value === null ? <span className="text-muted">not set</span> : truncate(value, 400)}
                        </TD>
                      ))}
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader
          title="Steps side by side"
          description={
            pairs.length === 0
              ? "Neither run has recorded steps."
              : divergence === null
                ? "Paired by position. Both runs made the same tool calls with the same outcomes; the model's wording is not compared."
                : `Paired by position; the model's wording is not compared. The runs first differ at row ${divergence + 1}.`
          }
        />
        {pairs.length > 0 ? (
          <Table className="min-w-[720px] table-fixed">
            <THead>
              <TR>
                <TH className="w-10">#</TH>
                <TH>A</TH>
                <TH>B</TH>
                <TH className="w-44">Relation</TH>
              </TR>
            </THead>
            <TBody>
              {pairs.map((pair) => (
                <TR key={pair.position} className={pair.position === divergence ? "bg-surface-2" : undefined}>
                  <TD className="tabular text-muted">{pair.position + 1}</TD>
                  <TD className="min-w-0">
                    <StepCell step={pair.a} />
                  </TD>
                  <TD className="min-w-0">
                    <StepCell step={pair.b} />
                  </TD>
                  <TD className={cn("text-xs", pair.relation === "same" ? "text-muted" : "text-ink")}>
                    {RELATION_LABELS[pair.relation]}
                    {pair.position === divergence ? <div className="text-ink-2">first difference</div> : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader title="Result of A" />
          <CardBody>
            <Answer run={a} />
          </CardBody>
        </Card>
        <Card className="min-w-0">
          <CardHeader title="Result of B" />
          <CardBody>
            <Answer run={b} />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function ComparePage() {
  const params = useSearchParams();
  const router = useRouter();
  const idA = params.get("a") ?? "";
  const idB = params.get("b") ?? "";
  const ready = idA !== "" && idB !== "";
  const runs = useApi(
    () => (ready ? Promise.all([api.run(idA), api.run(idB)]) : Promise.resolve(undefined)),
    [idA, idB],
    { pollMs: (data) => (data && data.some((r) => !isTerminal(r.status)) ? 2_000 : undefined) },
  );

  return (
    <>
      <PageHeader
        title="Compare runs"
        description="Two runs side by side: metrics, evaluation checks, configuration and tool calls."
        actions={
          ready ? (
            <Button variant="outline" onClick={() => router.replace(compareHref(idB, idA))}>
              <ArrowLeftRight aria-hidden className="size-3.5" /> Swap A and B
            </Button>
          ) : null
        }
      />
      {!ready ? (
        <Card>
          <Empty>
            Select two runs on the <Link href="/runs" className="underline">Runs</Link> page and choose Compare.
          </Empty>
        </Card>
      ) : runs.error ? (
        <ErrorState message={runs.error} />
      ) : !runs.data ? (
        <Loading />
      ) : (
        <Comparison a={runs.data[0]} b={runs.data[1]} />
      )}
    </>
  );
}

export default function Page() {
  // useSearchParams needs a Suspense boundary for the production build.
  return (
    <Suspense fallback={<Loading />}>
      <ComparePage />
    </Suspense>
  );
}
