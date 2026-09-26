"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { InlineBar } from "@/components/bars";
import { PageHeader } from "@/components/page-header";
import { RunStatusBadge } from "@/components/status";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatCost, relativeTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function BenchmarksPage() {
  const router = useRouter();
  const suites = useApi(() => api.suites(), []);
  const agents = useApi(() => api.agents(), []);
  const history = useApi(() => api.benchmarkRuns({ limit: 50 }), [], {
    pollMs: (data) => (data?.some((b) => b.status === "running" || b.status === "pending") ? 3_000 : 20_000),
  });
  const [suiteId, setSuiteId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [repeats, setRepeats] = useState("");
  const [error, setError] = useState<string>();

  const start = async () => {
    setError(undefined);
    try {
      const bench = await api.startBenchmark({
        suite_id: suiteId,
        agent_id: agentId,
        repeats: repeats ? Number(repeats) : undefined,
      });
      router.push(`/benchmarks/${bench.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (suites.error) return <ErrorState message={suites.error} />;

  return (
    <>
      <PageHeader
        title="Benchmarks"
        description="Repeatable task suites with initial state, allowed tools and success criteria."
      />
      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          <CardHeader title="Suites" description="Discovered in the server's benchmarks directory." />
          {!suites.data ? (
            <Loading />
          ) : suites.data.length === 0 ? (
            <Empty>No suites found.</Empty>
          ) : (
            <div className="divide-y divide-line">
              {suites.data.map((s) => (
                <details key={s.id} className="group px-4 py-3">
                  <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3">
                    <span>
                      <span className="font-medium text-ink">{s.name}</span>{" "}
                      <span className="font-mono text-xs text-muted">{s.id}</span>
                    </span>
                    <span className="text-xs text-ink-2">
                      {s.tasks.length} tasks · {s.repeats}× by default
                    </span>
                  </summary>
                  {s.description ? <p className="mt-1 text-xs text-muted">{s.description}</p> : null}
                  <Table className="mt-2">
                    <THead>
                      <TR>
                        <TH>Task</TH>
                        <TH>Goal</TH>
                        <TH>Tools</TH>
                        <TH className="text-right">Checks</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {s.tasks.map((t) => (
                        <TR key={t.id}>
                          <TD className="font-mono text-xs whitespace-nowrap">{t.id}</TD>
                          <TD className="text-ink-2">{t.goal}</TD>
                          <TD className="text-xs text-ink-2">{t.allowed_tools?.join(", ") ?? "agent's"}</TD>
                          <TD className="tabular text-right">{t.evaluators.length}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </details>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Run a benchmark" description="Uses a stored agent." />
          <CardBody className="space-y-3">
            <div>
              <Label htmlFor="suite">Suite</Label>
              <Select id="suite" value={suiteId} onChange={(e) => setSuiteId(e.target.value)}>
                <option value="">Select a suite…</option>
                {suites.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="agent">Agent</Label>
              <Select id="agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="">Select an agent…</option>
                {agents.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="repeats">Repeats (optional)</Label>
              <Input
                id="repeats"
                type="number"
                min={1}
                max={100}
                value={repeats}
                onChange={(e) => setRepeats(e.target.value)}
                placeholder="suite default"
              />
            </div>
            {error ? <p className="text-xs text-critical-text">{error}</p> : null}
            <Button className="w-full" disabled={!suiteId || !agentId} onClick={start}>
              Start benchmark
            </Button>
          </CardBody>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="History" />
        {!history.data ? (
          <Loading />
        ) : history.data.length === 0 ? (
          <Empty>No benchmark runs yet.</Empty>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Status</TH>
                <TH>Suite</TH>
                <TH>Agent</TH>
                <TH>Model</TH>
                <TH>Variant</TH>
                <TH className="text-right">Runs</TH>
                <TH>Pass rate</TH>
                <TH className="text-right">Cost</TH>
                <TH>Started</TH>
              </TR>
            </THead>
            <TBody>
              {history.data.map((b) => (
                <TR key={b.id} className="hover:bg-surface-2">
                  <TD>
                    <RunStatusBadge status={b.status} />
                  </TD>
                  <TD>
                    <Link href={`/benchmarks/${b.id}`} className="hover:underline">
                      {b.suite_name}
                    </Link>
                  </TD>
                  <TD>{b.agent_name}</TD>
                  <TD className="font-mono text-xs text-ink-2">
                    {b.agent_config.model.provider}/{b.agent_config.model.model || "-"}
                  </TD>
                  <TD className="text-ink-2">{b.variant ?? "—"}</TD>
                  <TD className="tabular text-right">
                    {b.results.length}
                    {b.summary ? "" : "…"}
                  </TD>
                  <TD>
                    <InlineBar value={b.summary?.pass_rate} />
                  </TD>
                  <TD className="tabular text-right">{formatCost(b.summary?.total_cost_usd)}</TD>
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
