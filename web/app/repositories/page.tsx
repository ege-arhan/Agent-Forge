"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { Issue } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

export default function RepositoriesPage() {
  const router = useRouter();
  const status = useApi(() => api.githubStatus(), []);
  const agents = useApi(() => api.agents(), []);
  const [input, setInput] = useState("");
  const [repo, setRepo] = useState<string>();
  const [info, setInfo] = useState<Record<string, unknown>>();
  const [issues, setIssues] = useState<Issue[]>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Issue>();
  const [agentId, setAgentId] = useState("");
  const [testCommand, setTestCommand] = useState("");
  const [push, setPush] = useState(false);
  const [openPr, setOpenPr] = useState(false);

  const load = async () => {
    if (!REPO_RE.test(input)) {
      setError("Enter a repository as owner/name.");
      return;
    }
    setLoading(true);
    setError(undefined);
    setSelected(undefined);
    try {
      const [repoInfo, repoIssues] = await Promise.all([api.githubRepo(input), api.githubIssues(input)]);
      setRepo(input);
      setInfo(repoInfo);
      setIssues(repoIssues);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const solve = async () => {
    if (!repo || !selected) return;
    setError(undefined);
    try {
      const run = await api.startGithubTask({
        repo,
        issue_number: selected.number,
        agent_id: agentId,
        test_command: testCommand || undefined,
        push,
        open_pr: push && openPr,
      });
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <>
      <PageHeader
        title="Repositories"
        description="Inspect a GitHub repository and turn an issue into an agent task."
      />
      {status.data && !status.data.token_configured ? (
        <p className="mb-4 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
          No GitHub token configured on the server (set <code className="font-mono">{status.data.token_env}</code>).
          Public repositories can still be read, subject to GitHub rate limits.
        </p>
      ) : null}
      <Card>
        <CardBody className="flex flex-wrap items-end gap-2">
          <div className="min-w-64 flex-1">
            <Label htmlFor="repo">Repository</Label>
            <Input
              id="repo"
              placeholder="owner/name"
              value={input}
              onChange={(e) => setInput(e.target.value.trim())}
              onKeyDown={(e) => e.key === "Enter" && load()}
            />
          </div>
          <Button onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Load"}
          </Button>
        </CardBody>
      </Card>
      {error ? (
        <div className="mt-4">
          <ErrorState message={error} />
        </div>
      ) : null}

      {repo && info ? (
        <div className="mt-5 grid gap-5 xl:grid-cols-3">
          <Card className="min-w-0 xl:col-span-2">
            <CardHeader title={`Open issues · ${repo}`} description="Select an issue to create a task." />
            {!issues ? (
              <Loading />
            ) : issues.length === 0 ? (
              <Empty>No open issues.</Empty>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH className="w-16">#</TH>
                    <TH>Title</TH>
                    <TH>Labels</TH>
                    <TH />
                  </TR>
                </THead>
                <TBody>
                  {issues.map((issue) => (
                    <TR key={issue.number} className={selected?.number === issue.number ? "bg-surface-2" : ""}>
                      <TD className="tabular">
                        <a href={issue.html_url} target="_blank" rel="noreferrer" className="hover:underline">
                          {issue.number}
                        </a>
                      </TD>
                      <TD>{issue.title}</TD>
                      <TD className="text-xs text-ink-2">{issue.labels.join(", ")}</TD>
                      <TD className="text-right">
                        <Button size="sm" variant="outline" onClick={() => setSelected(issue)}>
                          Select
                        </Button>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>
          <div className="space-y-5">
            <Card>
              <CardHeader title="Repository" />
              <CardBody>
                <dl className="space-y-1 text-[13px]">
                  {Object.entries(info).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[8rem_1fr] gap-2">
                      <dt className="text-muted">{k}</dt>
                      <dd className="break-words text-ink">{String(v ?? "—")}</dd>
                    </div>
                  ))}
                </dl>
              </CardBody>
            </Card>
            <Card>
              <CardHeader
                title={selected ? `Solve #${selected.number}` : "Solve an issue"}
                description="The agent works on a clone in its sandbox and never sees the token. Pull requests are drafts and are never merged."
              />
              <CardBody className="space-y-3">
                {!selected ? (
                  <p className="text-[13px] text-muted">Select an issue first.</p>
                ) : (
                  <>
                    <p className="text-[13px] text-ink">{selected.title}</p>
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
                      <Label htmlFor="tests">Test command (optional)</Label>
                      <Input
                        id="tests"
                        placeholder="pytest -q"
                        value={testCommand}
                        onChange={(e) => setTestCommand(e.target.value)}
                      />
                    </div>
                    <label className="flex items-center gap-2 text-[13px] text-ink">
                      <input type="checkbox" checked={push} onChange={(e) => setPush(e.target.checked)} />
                      Push the branch if the evaluation passes
                    </label>
                    <label className="flex items-center gap-2 text-[13px] text-ink">
                      <input
                        type="checkbox"
                        checked={openPr}
                        disabled={!push}
                        onChange={(e) => setOpenPr(e.target.checked)}
                      />
                      Open a draft pull request
                    </label>
                    <Button className="w-full" disabled={!agentId} onClick={solve}>
                      Start task
                    </Button>
                  </>
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      ) : null}
    </>
  );
}
