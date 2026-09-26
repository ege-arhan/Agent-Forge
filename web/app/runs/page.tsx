"use client";

import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { RunsTable } from "@/components/runs-table";
import { ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 50;
const STATUSES = ["", "running", "pending", "succeeded", "failed", "timed_out", "cancelled"];

export default function RunsPage() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const runs = useApi(() => api.runs({ status, limit: PAGE_SIZE, offset }), [status, offset], {
    pollMs: (data) =>
      data?.items.some((r) => r.status === "running" || r.status === "pending") ? 3_000 : 15_000,
  });

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every agent execution, including benchmark and GitHub runs."
        actions={
          <Select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
            className="w-40"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? s.replace("_", " ") : "All statuses"}
              </option>
            ))}
          </Select>
        }
      />
      {runs.error ? (
        <ErrorState message={runs.error} />
      ) : (
        <Card className={runs.refreshing ? "opacity-90" : undefined}>
          {!runs.data ? <Loading /> : <RunsTable runs={runs.data.items} />}
          {runs.data && runs.data.total > PAGE_SIZE ? (
            <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-ink-2">
              <span className="tabular">
                {offset + 1}–{Math.min(offset + PAGE_SIZE, runs.data.total)} of {runs.data.total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset + PAGE_SIZE >= runs.data.total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </Card>
      )}
    </>
  );
}
