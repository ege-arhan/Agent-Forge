"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { RunStatusBadge } from "@/components/status";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, request } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { Experiment } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const VARIANTS_TEMPLATE = JSON.stringify(
  [
    { name: "baseline" },
    { name: "plan-execute", overrides: { planner: { strategy: "plan_execute" } } },
  ],
  null,
  2,
);

export default function ExperimentsPage() {
  const router = useRouter();
  const experiments = useApi(() => api.experiments(), [], {
    pollMs: (d) => (d?.some((e) => e.status === "running") ? 3_000 : 20_000),
  });
  const suites = useApi(() => api.suites(), []);
  const agents = useApi(() => api.agents(), []);
  const [name, setName] = useState("");
  const [suiteId, setSuiteId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [repeats, setRepeats] = useState("3");
  const [variants, setVariants] = useState(VARIANTS_TEMPLATE);
  const [error, setError] = useState<string>();

  const start = async () => {
    setError(undefined);
    let parsed: unknown;
    try {
      parsed = JSON.parse(variants);
    } catch {
      setError("Variants must be a JSON array.");
      return;
    }
    try {
      const exp = await request<Experiment>("/experiments", {
        method: "POST",
        body: {
          name,
          suite_id: suiteId,
          base_agent_id: agentId,
          variants: parsed,
          repeats: repeats ? Number(repeats) : undefined,
        },
      });
      router.push(`/experiments/${exp.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (experiments.error) return <ErrorState message={experiments.error} />;

  return (
    <>
      <PageHeader
        title="Experiments"
        description="Compare agent variants (model, prompt, tools, planner, limits) on the same suite."
      />
      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          {!experiments.data ? (
            <Loading />
          ) : experiments.data.length === 0 ? (
            <Empty>No experiments yet.</Empty>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Status</TH>
                  <TH>Name</TH>
                  <TH>Suite</TH>
                  <TH>Variants</TH>
                  <TH>Started</TH>
                </TR>
              </THead>
              <TBody>
                {experiments.data.map((e) => (
                  <TR key={e.id} className="hover:bg-surface-2">
                    <TD>
                      <RunStatusBadge status={e.status} />
                    </TD>
                    <TD>
                      <Link href={`/experiments/${e.id}`} className="font-medium hover:underline">
                        {e.name}
                      </Link>
                      {e.description ? <div className="text-xs text-muted">{e.description}</div> : null}
                    </TD>
                    <TD className="font-mono text-xs text-ink-2">{e.suite_id}</TD>
                    <TD className="text-ink-2">{e.spec.variants.map((v) => v.name).join(", ")}</TD>
                    <TD className="text-ink-2">{relativeTime(e.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="New experiment" description="Variants are deep-merged into the base agent config." />
          <CardBody className="space-y-3">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
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
              <Label htmlFor="agent">Base agent</Label>
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
              <Label htmlFor="repeats">Repeats</Label>
              <Input id="repeats" type="number" min={1} value={repeats} onChange={(e) => setRepeats(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="variants">Variants (first = baseline)</Label>
              <Textarea
                id="variants"
                value={variants}
                onChange={(e) => setVariants(e.target.value)}
                className="min-h-40 font-mono text-xs"
                spellCheck={false}
              />
            </div>
            {error ? <p className="text-xs text-critical-text">{error}</p> : null}
            <Button className="w-full" disabled={!name || !suiteId || !agentId} onClick={start}>
              Start experiment
            </Button>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
