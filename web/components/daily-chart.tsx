"use client";

import { useState } from "react";

import { barHeight, formatDay, labelIndexes, niceScale } from "@/lib/timeseries";

export interface DailyChartPoint {
  date: string;
  /** null = unknown for that day (drawn as no bar, named in the tooltip). */
  value: number | null;
  /** Tooltip lines under the headline value. */
  detail?: string[];
}

/**
 * One measure per day as thin columns on a single zero-based axis. One series,
 * so no legend: the title names it. Hovering (or touching) a day shows its
 * exact figures; the same numbers are in the table under the charts.
 */
export function DailyChart({
  title,
  summary,
  points,
  format,
  integer = false,
  unit,
}: {
  title: string;
  summary: string;
  points: DailyChartPoint[];
  format: (value: number | null) => string;
  integer?: boolean;
  /** Axis unit: values are divided by `per` for the scale and ticks read `<n><suffix>`. */
  unit?: { per: number; suffix: string };
}) {
  const [active, setActive] = useState<number | null>(null);
  const peak = points.reduce((max, p) => Math.max(max, p.value ?? 0), 0);
  const per = unit?.per ?? 1;
  const scale = niceScale(peak / per, integer);
  const tickLabel = (tick: number) => (unit ? `${tick}${unit.suffix}` : format(tick));
  const labelled = new Set(labelIndexes(points.length));
  const hovered = active !== null ? points[active] : undefined;
  // Keep the tooltip inside the plot: anchor it left, centre or right of the day.
  const position = active === null || points.length <= 1 ? 0.5 : active / (points.length - 1);
  const anchor =
    position < 0.25 ? "translate-x-0" : position > 0.75 ? "-translate-x-full" : "-translate-x-1/2";

  return (
    <figure className="min-w-0">
      <figcaption>
        <div className="text-xs font-medium text-ink">{title}</div>
        <div className="mt-0.5 text-xs text-muted">{summary}</div>
      </figcaption>
      <div className="mt-3 flex gap-2">
        <div className="relative h-28 w-9 shrink-0" aria-hidden>
          {scale.ticks.map((tick) => (
            <span
              key={tick}
              className="tabular absolute right-0 translate-y-1/2 text-[10px] leading-none whitespace-nowrap text-muted"
              style={{ bottom: `${(tick / scale.max) * 100}%` }}
            >
              {tickLabel(tick)}
            </span>
          ))}
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative h-28" onPointerLeave={() => setActive(null)}>
            {scale.ticks.map((tick) => (
              <div
                key={tick}
                aria-hidden
                className={`absolute inset-x-0 h-px ${tick === 0 ? "bg-axis" : "bg-grid"}`}
                style={{ bottom: `${(tick / scale.max) * 100}%` }}
              />
            ))}
            <div className="absolute inset-0 flex" role="img" aria-label={`${title}: ${summary}`}>
              {points.map((point, index) => {
                const height = barHeight(point.value, scale.max * per);
                return (
                  <div
                    key={point.date}
                    className={`flex h-full min-w-0 flex-1 items-end justify-center ${
                      active === index ? "bg-surface-2" : ""
                    }`}
                    onPointerEnter={() => setActive(index)}
                    onPointerDown={() => setActive(index)}
                  >
                    {height > 0 ? (
                      <div
                        className="bar-fill w-full max-w-6 rounded-t bg-series-1"
                        style={{ height: `max(2px, ${height}%)`, marginInline: "min(1px, 10%)" }}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
            {hovered ? (
              <div
                role="status"
                className={`pointer-events-none absolute bottom-full z-10 mb-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs whitespace-nowrap shadow-sm ${anchor}`}
                style={{ left: `${((active! + 0.5) / points.length) * 100}%` }}
              >
                <div className="text-muted">{formatDay(hovered.date)}</div>
                <div className="tabular font-semibold text-ink">{format(hovered.value)}</div>
                {hovered.detail?.map((line) => (
                  <div key={line} className="tabular text-ink-2">
                    {line}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="relative mt-1 h-4" aria-hidden>
            {points.map((point, index) =>
              labelled.has(index) ? (
                <span
                  key={point.date}
                  className={`absolute text-[10px] whitespace-nowrap text-muted ${
                    index === 0
                      ? ""
                      : index === points.length - 1
                        ? "-translate-x-full"
                        : "-translate-x-1/2"
                  }`}
                  style={{
                    left:
                      index === 0
                        ? 0
                        : index === points.length - 1
                          ? "100%"
                          : `${((index + 0.5) / points.length) * 100}%`,
                  }}
                >
                  {formatDay(point.date)}
                </span>
              ) : null,
            )}
          </div>
        </div>
      </div>
    </figure>
  );
}
