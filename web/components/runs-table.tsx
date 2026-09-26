import Link from "next/link";

import { EvalBadge, RunStatusBadge } from "@/components/status";
import { Empty } from "@/components/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatCost, formatDuration, formatNumber, relativeTime, truncate } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

export function RunsTable({ runs, compact = false }: { runs: RunSummary[]; compact?: boolean }) {
  if (runs.length === 0) return <Empty>No runs yet.</Empty>;
  return (
    <Table>
      <THead>
        <TR>
          <TH>Status</TH>
          <TH>Goal</TH>
          <TH>Agent</TH>
          {!compact && <TH>Model</TH>}
          <TH>Evaluation</TH>
          <TH className="text-right">Steps</TH>
          <TH className="text-right">Duration</TH>
          {!compact && <TH className="text-right">Cost</TH>}
          <TH>Started</TH>
        </TR>
      </THead>
      <TBody>
        {runs.map((run) => (
          <TR key={run.id} className="hover:bg-surface-2">
            <TD>
              <RunStatusBadge status={run.status} />
            </TD>
            <TD className="max-w-md">
              <Link href={`/runs/${run.id}`} className="line-clamp-2 text-ink hover:underline">
                {truncate(run.goal.split("\n")[0] ?? run.goal, compact ? 70 : 110)}
              </Link>
              {run.error_type ? <div className="text-xs text-critical-text">{run.error_type}</div> : null}
            </TD>
            <TD className="whitespace-nowrap text-ink-2">{run.agent_name}</TD>
            {!compact && (
              <TD className="font-mono text-xs whitespace-nowrap text-ink-2">
                {run.provider}/{run.model || "-"}
              </TD>
            )}
            <TD className="whitespace-nowrap">
              <EvalBadge passed={run.passed} />
              {run.score !== null ? (
                <span className="tabular ml-1 text-xs text-muted">{formatNumber(run.score)}</span>
              ) : null}
            </TD>
            <TD className="tabular text-right">{run.steps}</TD>
            <TD className="tabular text-right whitespace-nowrap">{formatDuration(run.duration_seconds)}</TD>
            {!compact && <TD className="tabular text-right">{formatCost(run.cost_usd)}</TD>}
            <TD className="whitespace-nowrap text-ink-2">{relativeTime(run.created_at)}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
