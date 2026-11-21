"use client";

import { GitCompareArrows } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { RunsTable } from "@/components/runs-table";
import { ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { compareHref, MAX_COMPARED, toggleSelection } from "@/lib/compare";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 50;
const STATUSES = ["", "running", "pending", "succeeded", "failed", "timed_out", "cancelled"];

export default function RunsPage() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  // Ids picked for comparison; kept across pages and filters.
  const [selected, setSelected] = useState<string[]>([]);
  const router = useRouter();
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
          <>
            <Button
              variant="outline"
              disabled={selected.length !== MAX_COMPARED}
              title="Tick two runs in the table to compare them"
              onClick={() => router.push(compareHref(selected[0] ?? "", selected[1] ?? ""))}
            >
              <GitCompareArrows aria-hidden className="size-3.5" /> Compare ({selected.length}/{MAX_COMPARED})
            </Button>
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
          </>
        }
      />
      {runs.error ? (
        <ErrorState message={runs.error} />
      ) : (
        <Card className={runs.refreshing ? "opacity-90" : undefined}>
          {!runs.data ? <Loading /> : (
            <RunsTable
              runs={runs.data.items}
              selection={{ selected, onToggle: (id) => setSelected((ids) => toggleSelection(ids, id)) }}
            />
          )}
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
