"use client";

import { Play, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { RunsTable } from "@/components/runs-table";
import { ErrorState, Loading } from "@/components/states";
import { Pre } from "@/components/trace";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Label, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const agent = useApi(() => api.agent(id), [id]);
  const runs = useApi(() => api.runs({ agent_id: id, limit: 20 }), [id], { pollMs: 10_000 });
  const [goal, setGoal] = useState("");
  const [evaluators, setEvaluators] = useState("[]");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  if (agent.error) return <ErrorState message={agent.error} />;
  if (!agent.data) return <Loading />;
  const a = agent.data;

  const start = async () => {
    setError(undefined);
    let specs: unknown[];
    try {
      specs = JSON.parse(evaluators || "[]") as unknown[];
      if (!Array.isArray(specs)) throw new Error();
    } catch {
      setError("Evaluators must be a JSON array, e.g. [{\"type\": \"command\", \"command\": \"pytest -q\"}].");
      return;
    }
    setBusy(true);
    try {
      const run = await api.createRun({ agent_id: a.id, goal, evaluators: specs });
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete agent "${a.name}"? Its runs are kept.`)) return;
    try {
      await api.deleteAgent(a.id);
      router.push("/agents");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <>
      <PageHeader
        title={a.name}
        description={
          <span className="flex flex-wrap gap-x-3">
            <span className="font-mono text-xs">
              {a.config.model.provider}/{a.config.model.model || "-"}
            </span>
            <span>v{a.version}</span>
            {a.description ? <span>{a.description}</span> : null}
          </span>
        }
        actions={
          <Button variant="danger" onClick={remove}>
            <Trash2 aria-hidden className="size-3.5" /> Delete
          </Button>
        }
      />
      <div className="grid gap-5 xl:grid-cols-3">
        <div className="space-y-5 xl:col-span-2">
          <Card>
            <CardHeader title="Start a run" description="Runs execute in the background on the API server." />
            <CardBody className="space-y-3">
              <div>
                <Label htmlFor="goal">Goal</Label>
                <Textarea
                  id="goal"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="Describe what the agent should accomplish…"
                />
              </div>
              <div>
                <Label htmlFor="evaluators">Evaluators (JSON array, optional)</Label>
                <Textarea
                  id="evaluators"
                  value={evaluators}
                  onChange={(e) => setEvaluators(e.target.value)}
                  className="min-h-16 font-mono text-xs"
                  spellCheck={false}
                />
              </div>
              {error ? <p className="text-xs text-critical-text">{error}</p> : null}
              <div className="flex justify-end">
                <Button onClick={start} disabled={busy || !goal.trim()}>
                  <Play aria-hidden className="size-3.5" /> Run agent
                </Button>
              </div>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Runs of this agent" />
            {!runs.data ? <Loading /> : <RunsTable runs={runs.data.items} compact />}
          </Card>
        </div>
        <Card>
          <CardHeader title="Configuration" />
          <CardBody>
            <Pre className="max-h-[40rem]">{JSON.stringify(a.config, null, 2)}</Pre>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
