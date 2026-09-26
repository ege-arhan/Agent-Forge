"use client";

import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { AgentConfig } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const TEMPLATE = JSON.stringify(
  {
    name: "my-agent",
    description: "What this agent is for",
    model: { provider: "anthropic", model: "claude-opus-5", max_tokens: 16000 },
    system_prompt: "You are a careful software engineer. Verify your work before finishing.",
    tools: ["filesystem", "terminal"],
    limits: { max_steps: 30, timeout_seconds: 900 },
    sandbox: { kind: "docker", image: "python:3.12-slim" },
  },
  null,
  2,
);

export default function AgentsPage() {
  const agents = useApi(() => api.agents(), []);
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState(TEMPLATE);
  const [formError, setFormError] = useState<string>();

  const create = async () => {
    setFormError(undefined);
    let config: AgentConfig;
    try {
      config = JSON.parse(draft) as AgentConfig;
    } catch {
      setFormError("The configuration is not valid JSON.");
      return;
    }
    try {
      await api.createAgent(config);
      setShowForm(false);
      agents.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <>
      <PageHeader
        title="Agents"
        description="Stored, versioned agent configurations."
        actions={<Button onClick={() => setShowForm(!showForm)}>{showForm ? "Close" : "New agent"}</Button>}
      />
      {showForm ? (
        <Card className="mb-5">
          <CardHeader
            title="New agent"
            description={
              <>
                Paste an agent configuration as JSON. YAML files can be imported with{" "}
                <code className="font-mono">agentforge agents create FILE.yaml</code>.
              </>
            }
          />
          <CardBody>
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-72 font-mono text-xs"
              spellCheck={false}
              aria-label="Agent configuration JSON"
            />
            {formError ? <p className="mt-2 text-xs text-critical-text">{formError}</p> : null}
            <div className="mt-3 flex justify-end">
              <Button onClick={create}>Create agent</Button>
            </div>
          </CardBody>
        </Card>
      ) : null}
      {agents.error ? (
        <ErrorState message={agents.error} />
      ) : (
        <Card>
          {!agents.data ? (
            <Loading />
          ) : agents.data.length === 0 ? (
            <Empty>No agents yet. Create one here or with the CLI.</Empty>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Model</TH>
                  <TH>Tools</TH>
                  <TH>Planner</TH>
                  <TH>Sandbox</TH>
                  <TH className="text-right">Version</TH>
                  <TH>Updated</TH>
                </TR>
              </THead>
              <TBody>
                {agents.data.map((a) => (
                  <TR key={a.id} className="hover:bg-surface-2">
                    <TD>
                      <Link href={`/agents/${a.id}`} className="font-medium hover:underline">
                        {a.name}
                      </Link>
                      {a.description ? <div className="text-xs text-muted">{a.description}</div> : null}
                    </TD>
                    <TD className="font-mono text-xs text-ink-2">
                      {a.config.model.provider}/{a.config.model.model || "-"}
                    </TD>
                    <TD className="text-ink-2">{a.config.tools.join(", ") || "—"}</TD>
                    <TD className="text-ink-2">{a.config.planner.strategy}</TD>
                    <TD className="text-ink-2">{a.config.sandbox.kind}</TD>
                    <TD className="tabular text-right">v{a.version}</TD>
                    <TD className="text-ink-2">{relativeTime(a.updated_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      )}
    </>
  );
}
