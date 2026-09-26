import { barWidth, formatPercent } from "@/lib/format";

/**
 * Inline magnitude bar for table cells (one series, categorical slot 1).
 * The value is always printed next to the bar, so the table is the table view.
 */
export function InlineBar({ value, label }: { value: number | null | undefined; label?: string }) {
  const width = barWidth(value);
  const text = label ?? formatPercent(value);
  return (
    <div className="flex min-w-32 items-center gap-2" title={text}>
      <div className="relative h-2 flex-1 rounded-full bg-surface-2" aria-hidden>
        {value !== null && value !== undefined ? (
          <div
            className="bar-fill absolute inset-y-0 left-0 rounded-full bg-series-1"
            style={{ width: `${width}%` }}
          />
        ) : null}
      </div>
      <span className="tabular w-11 shrink-0 text-right text-xs text-ink-2">{text}</span>
    </div>
  );
}

/**
 * Pass rate with a 95% confidence-interval whisker. The whisker is drawn in
 * secondary ink over the rate bar; the exact numbers are printed alongside.
 */
export function RateWithInterval({
  rate,
  interval,
}: {
  rate: number;
  interval: [number, number] | null;
}) {
  const ciText = interval ? `${formatPercent(interval[0])}–${formatPercent(interval[1])}` : "n/a";
  return (
    <div className="flex min-w-48 items-center gap-2" title={`pass rate ${formatPercent(rate)}, 95% CI ${ciText}`}>
      <div className="relative h-3 flex-1" aria-hidden>
        <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-surface-2" />
        <div
          className="bar-fill absolute top-1/2 left-0 h-2 -translate-y-1/2 rounded-full bg-series-1"
          style={{ width: `${barWidth(rate)}%` }}
        />
        {interval ? (
          <>
            <div
              className="absolute top-1/2 h-px -translate-y-1/2 bg-ink-2"
              style={{ left: `${barWidth(interval[0])}%`, width: `${barWidth(interval[1]) - barWidth(interval[0])}%` }}
            />
            <div className="absolute top-0 h-3 w-px bg-ink-2" style={{ left: `${barWidth(interval[0])}%` }} />
            <div className="absolute top-0 h-3 w-px bg-ink-2" style={{ left: `calc(${barWidth(interval[1])}% - 1px)` }} />
          </>
        ) : null}
      </div>
      <span className="tabular w-11 shrink-0 text-right text-xs text-ink">{formatPercent(rate)}</span>
    </div>
  );
}
