"use client";

import { RotateCcw, Square } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { ErrorState, Loading } from "@/components/states";
import { StatTile } from "@/components/stat-tile";
import { EvalBadge, RunStatusBadge } from "@/components/status";
import { Pre, Trace } from "@/components/trace";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
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
import { useApi } from "@/lib/use-api";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 py-1 text-[13px]">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{children}</dd>
    </div>
  );
}

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [actionError, setActionError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const run = useApi(() => api.run(id), [id], {
    pollMs: (data) => (data && !isTerminal(data.status) ? 1_500 : undefined),
  });

  if (run.error) return <ErrorState message={run.error} />;
  if (!run.data) return <Loading />;
  const r = run.data;
  const m = r.metrics;
  const active = !isTerminal(r.status);

  const act = async (fn: () => Promise<{ id: string }>, navigate: boolean) => {
    setBusy(true);
    setActionError(undefined);
    try {
      const result = await fn();
      if (navigate) router.push(`/runs/${result.id}`);
      else run.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const liveSteps = r.steps.filter((s) => s.kind === "action").length;
  const liveToolCalls = r.steps.reduce((n, s) => n + s.tool_calls.length, 0);

  return (
    <>
      <PageHeader
        title={truncate(r.goal.split("\n")[0] ?? r.goal, 120)}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <RunStatusBadge status={r.status} />
            <span>
              {r.agent_id ? (
                <Link href={`/agents/${r.agent_id}`} className="hover:underline">
                  {r.agent_name}
                </Link>
              ) : (
                r.agent_name
              )}
            </span>
            <span className="font-mono text-xs">
              {r.config.model.provider}/{r.config.model.model || "-"}
            </span>
            <span>{relativeTime(r.created_at)}</span>
          </span>
        }
        actions={
          <>
            {active ? (
              <Button variant="danger" disabled={busy} onClick={() => act(() => api.cancelRun(r.id), false)}>
                <Square aria-hidden className="size-3.5" /> Cancel
              </Button>
            ) : null}
            <Button variant="outline" disabled={busy} onClick={() => act(() => api.rerun(r.id), true)}>
              <RotateCcw aria-hidden className="size-3.5" /> Re-run
            </Button>
          </>
        }
      />
      {actionError ? (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Duration" value={formatDuration(m.duration_seconds)} />
        <StatTile label="Steps" value={active ? liveSteps : m.steps} hint={`limit ${r.config.limits.max_steps}`} />
        <StatTile
          label="Tool calls"
          value={active ? liveToolCalls : m.tool_calls}
          hint={`success ${formatPercent(m.tool_success_rate)}`}
        />
        <StatTile label="LLM retries" value={m.llm_retries} hint={`${m.llm_calls} calls`} />
        <StatTile
          label="Tokens"
          value={formatTokens(r.usage.input_tokens + r.usage.output_tokens)}
          hint={`${formatTokens(r.usage.input_tokens)} in / ${formatTokens(r.usage.output_tokens)} out`}
        />
        <StatTile label="Estimated cost" value={formatCost(m.cost_usd)} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          <CardHeader
            title="Execution trace"
            description="Model turns, tool calls with arguments and outputs, evaluations and errors."
          />
          <CardBody>
            <Trace steps={r.steps} />
          </CardBody>
        </Card>

        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader
              title="Evaluation"
              action={r.evaluation ? <EvalBadge passed={r.evaluation.passed} /> : null}
            />
            <CardBody>
              {r.evaluation ? (
                <>
                  <div className="mb-2 text-xs text-muted">
                    Score <span className="tabular text-ink">{formatNumber(r.evaluation.score)}</span> (weighted
                    mean)
                  </div>
                  <ul className="space-y-2">
                    {r.evaluation.results.map((e) => (
                      <li key={e.name} className="text-[13px]">
                        <div className="flex items-center gap-2">
                          <EvalBadge passed={e.passed} />
                          <span className="font-mono text-xs">{e.name}</span>
                          {!e.required ? <span className="text-xs text-muted">optional</span> : null}
                        </div>
                        {e.details ? (
                          <p className="mt-0.5 pl-5 text-xs whitespace-pre-wrap text-muted [overflow-wrap:anywhere]">
                            {truncate(e.details, 600)}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="text-[13px] text-muted">
                  {r.evaluators.length ? "Pending evaluation." : "No evaluators configured for this run."}
                </p>
              )}
            </CardBody>
          </Card>

          {r.error ? (
            <Card>
              <CardHeader title="Error" />
              <CardBody>
                <p className="font-mono text-xs text-critical-text">{r.error.type}</p>
                <p className="mt-1 text-[13px] text-ink [overflow-wrap:anywhere]">{r.error.message}</p>
                {r.error.retryable ? <p className="mt-1 text-xs text-muted">Marked retryable.</p> : null}
              </CardBody>
            </Card>
          ) : null}

          <Card>
            <CardHeader title="Result" />
            <CardBody>
              {r.result ? (
                <p className="text-[13px] whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">{r.result}</p>
              ) : (
                <p className="text-[13px] text-muted">{active ? "Running…" : "No final answer."}</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Details" />
            <CardBody>
              <dl>
                <Field label="Run ID">
                  <span className="font-mono text-xs">{r.id}</span>
                </Field>
                {r.parent_run_id ? (
                  <Field label="Re-run of">
                    <Link href={`/runs/${r.parent_run_id}`} className="font-mono text-xs hover:underline">
                      {r.parent_run_id}
                    </Link>
                  </Field>
                ) : null}
                <Field label="Planner">{r.config.planner.strategy}</Field>
                <Field label="Sandbox">
                  {r.config.sandbox.kind}
                  {r.config.sandbox.kind === "docker" ? ` · ${r.config.sandbox.image}` : " (no isolation)"}
                </Field>
                <Field label="Tools">{r.config.tools.join(", ") || "none"}</Field>
                <Field label="Workspace">
                  <span className="font-mono text-xs">{r.workspace ?? "—"}</span>
                </Field>
                {Object.entries(r.labels).map(([k, v]) => (
                  <Field key={k} label={k}>
                    {v.startsWith("https://") ? (
                      <a href={v} className="hover:underline" target="_blank" rel="noreferrer">
                        {v}
                      </a>
                    ) : (
                      v
                    )}
                  </Field>
                ))}
              </dl>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Goal" />
            <CardBody>
              <p className="text-[13px] whitespace-pre-wrap text-ink">{r.goal}</p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Configuration snapshot" description="Exact config used; re-runs reuse it." />
            <CardBody>
              <Pre>{JSON.stringify(r.config, null, 2)}</Pre>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
