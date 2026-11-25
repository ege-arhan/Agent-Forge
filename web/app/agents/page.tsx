"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { draftFormat, importProblem, readDraft } from "@/lib/agent-import";
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
  const [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const importFile = async (file: File | undefined) => {
    if (!file) return;
    setNotice(undefined);
    const problem = importProblem(file);
    if (problem) {
      setFormError(problem);
      return;
    }
    try {
      setDraft(await file.text());
      setFormError(undefined);
      setNotice(`Loaded ${file.name}. Nothing is stored until you create the agent.`);
    } catch {
      setFormError(`${file.name} could not be read.`);
    }
  };

  const create = async () => {
    setFormError(undefined);
    setNotice(undefined);
    const parsed = readDraft(draft);
    if (parsed.kind === "empty") {
      setFormError("Paste or import a configuration first.");
      return;
    }
    if (parsed.kind === "json-error") {
      setFormError(parsed.message);
      return;
    }
    setBusy(true);
    try {
      // YAML is read by the API (the parser the CLI uses), then stored as usual.
      const config: AgentConfig =
        parsed.kind === "json" ? parsed.config : await api.parseAgentConfig(parsed.content);
      await api.createAgent(config);
      setShowForm(false);
      setDraft(TEMPLATE);
      agents.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const format = draftFormat(draft);

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
                Paste an agent configuration as JSON or YAML, or import a file — the same files{" "}
                <code className="font-mono">agentforge agents create FILE.yaml</code> reads.
              </>
            }
          />
          <CardBody>
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-72 font-mono text-xs"
              spellCheck={false}
              aria-label="Agent configuration (JSON or YAML)"
            />
            {formError ? (
              <p role="alert" className="mt-2 whitespace-pre-wrap break-words text-xs text-critical-text">
                {formError}
              </p>
            ) : null}
            {notice ? (
              <p role="status" className="mt-2 text-xs text-muted">
                {notice}
              </p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-3">
                <input
                  ref={fileInput}
                  type="file"
                  accept=".yaml,.yml,.json,application/json,application/yaml,text/yaml"
                  className="sr-only"
                  tabIndex={-1}
                  aria-label="Agent configuration file"
                  onChange={(e) => {
                    void importFile(e.target.files?.[0]);
                    e.target.value = ""; // choosing the same file again must fire a change
                  }}
                />
                <Button variant="outline" onClick={() => fileInput.current?.click()}>
                  Import file…
                </Button>
                {format ? <span className="text-xs text-muted">Read as {format}</span> : null}
              </div>
              <Button onClick={create} disabled={busy}>
                {busy ? "Creating…" : "Create agent"}
              </Button>
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
