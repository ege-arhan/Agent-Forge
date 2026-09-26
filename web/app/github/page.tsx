"use client";

import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { EvalBadge, RunStatusBadge } from "@/components/status";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatDuration, relativeTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function GitHubTasksPage() {
  const tasks = useApi(() => api.githubTasks(), [], {
    pollMs: (d) => (d?.items.some((r) => r.status === "running" || r.status === "pending") ? 3_000 : 20_000),
  });
  if (tasks.error) return <ErrorState message={tasks.error} />;
  return (
    <>
      <PageHeader
        title="GitHub tasks"
        description="Issue → analysis → implementation → tests → evaluation → branch → commit → draft PR."
      />
      <Card>
        {!tasks.data ? (
          <Loading />
        ) : tasks.data.items.length === 0 ? (
          <Empty>
            No GitHub tasks yet. Start one from{" "}
            <Link href="/repositories" className="underline">
              Repositories
            </Link>{" "}
            or with <code className="font-mono">agentforge github solve</code>.
          </Empty>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Issue</TH>
                <TH>Status</TH>
                <TH>Evaluation</TH>
                <TH>Branch</TH>
                <TH className="text-right">Commits</TH>
                <TH>Pull request</TH>
                <TH className="text-right">Duration</TH>
                <TH>Started</TH>
              </TR>
            </THead>
            <TBody>
              {tasks.data.items.map((r) => (
                <TR key={r.id} className="hover:bg-surface-2">
                  <TD>
                    <Link href={`/runs/${r.id}`} className="hover:underline">
                      {r.labels.github_repo}#{r.labels.github_issue}
                    </Link>
                  </TD>
                  <TD>
                    <RunStatusBadge status={r.status} />
                  </TD>
                  <TD>
                    <EvalBadge passed={r.passed} />
                  </TD>
                  <TD className="font-mono text-xs text-ink-2">{r.labels.branch ?? "—"}</TD>
                  <TD className="tabular text-right">{r.labels.commits ?? "—"}</TD>
                  <TD>
                    {r.labels.pr_url ? (
                      <a href={r.labels.pr_url} target="_blank" rel="noreferrer" className="hover:underline">
                        draft PR
                      </a>
                    ) : (
                      <span className="text-muted">{r.labels.pushed ? "pushed" : "not opened"}</span>
                    )}
                  </TD>
                  <TD className="tabular text-right">{formatDuration(r.duration_seconds)}</TD>
                  <TD className="text-ink-2">{relativeTime(r.created_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
