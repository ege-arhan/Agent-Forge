import type { ReactNode } from "react";

/** A KPI: the number is the chart. Proportional figures, system sans. */
export function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-ink-2">{hint}</div> : null}
    </div>
  );
}
