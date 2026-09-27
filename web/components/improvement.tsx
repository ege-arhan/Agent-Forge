import {
  Ban,
  CircleCheck,
  CircleHelp,
  CircleX,
  ClipboardList,
  Cpu,
  FileText,
  GitCommitHorizontal,
  LoaderCircle,
  Minus,
  TrendingDown,
  TrendingUp,
  Undo2,
  type LucideIcon,
} from "lucide-react";

import { categoryLabel, categoryRows, NON_AGENT_CATEGORIES } from "@/lib/improvement";
import type { CycleStatus, ResultClass, Verdict } from "@/lib/types";
import { cn } from "@/lib/utils";

// Same convention as components/status.tsx: icon + text label, colour only on the icon.
interface Spec {
  label: string;
  icon: LucideIcon;
  iconClass: string;
  spin?: boolean;
}

function Pill({ spec, className, title }: { spec: Spec; className?: string; title?: string }) {
  const Icon = spec.icon;
  return (
    <span
      title={title}
      className={cn("inline-flex items-center gap-1 text-[13px] whitespace-nowrap text-ink-2", className)}
    >
      <Icon aria-hidden className={cn("size-3.5 shrink-0", spec.iconClass, spec.spin && "animate-spin")} />
      {spec.label}
    </span>
  );
}

const RESULT_CLASS: Record<ResultClass, Spec> = {
  offline: { label: "Offline · scripted", icon: ClipboardList, iconClass: "text-muted" },
  real: { label: "Real model", icon: Cpu, iconClass: "text-series-1" },
};

export function ResultClassBadge({ value }: { value: ResultClass }) {
  return (
    <Pill
      spec={RESULT_CLASS[value]}
      title={
        value === "offline"
          ? "Deterministic scripted provider: validates the pipeline and benchmark, not a model"
          : "Produced by a real model provider"
      }
    />
  );
}

const VERDICT: Record<Verdict, Spec> = {
  improved: { label: "Improved", icon: TrendingUp, iconClass: "text-good" },
  regressed: { label: "Regressed", icon: TrendingDown, iconClass: "text-critical" },
  unchanged: { label: "Unchanged", icon: Minus, iconClass: "text-muted" },
  inconclusive: { label: "Inconclusive", icon: CircleHelp, iconClass: "text-warning" },
  not_comparable: { label: "Not comparable", icon: Ban, iconClass: "text-muted" },
};

export function VerdictBadge({ verdict }: { verdict: Verdict | null | undefined }) {
  if (!verdict) return <span className="text-[13px] text-muted">—</span>;
  return <Pill spec={VERDICT[verdict]} />;
}

const CYCLE_STATUS: Record<CycleStatus, Spec> = {
  proposed: { label: "Proposed", icon: FileText, iconClass: "text-muted" },
  applied: { label: "Applied", icon: GitCommitHorizontal, iconClass: "text-series-1" },
  evaluating: { label: "Evaluating", icon: LoaderCircle, iconClass: "text-series-1", spin: true },
  evaluated: { label: "Evaluated", icon: CircleCheck, iconClass: "text-good" },
  rejected: { label: "Rejected", icon: Undo2, iconClass: "text-muted" },
  failed: { label: "Failed", icon: CircleX, iconClass: "text-critical" },
};

export function CycleStatusBadge({ status }: { status: CycleStatus }) {
  return <Pill spec={CYCLE_STATUS[status] ?? CYCLE_STATUS.proposed} />;
}

/** Failure categories as a sorted bar list (one series; counts printed). */
export function CategoryBars({ counts }: { counts: Record<string, number> }) {
  const rows = categoryRows(counts);
  if (rows.length === 0) return <p className="text-[13px] text-muted">No failures.</p>;
  const max = Math.max(...rows.map((r) => r.count));
  return (
    <ul className="space-y-1.5">
      {rows.map((row) => (
        <li key={row.category} className="grid grid-cols-[minmax(9rem,12rem)_1fr_2.5rem] items-center gap-2">
          <span className="truncate text-[13px] text-ink-2" title={row.category}>
            {categoryLabel(row.category)}
            {NON_AGENT_CATEGORIES.has(row.category) ? <span className="text-muted"> · env</span> : null}
          </span>
          <span className="relative h-2 rounded-full bg-surface-2" aria-hidden>
            <span
              className="bar-fill absolute inset-y-0 left-0 rounded-full bg-series-1"
              style={{ width: `${(row.count / max) * 100}%` }}
            />
          </span>
          <span className="tabular text-right text-xs text-ink">{row.count}</span>
        </li>
      ))}
    </ul>
  );
}
