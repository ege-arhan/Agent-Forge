import "./mocks";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Activity } from "@/components/activity";
import { api } from "@/lib/api";

import { dailyPoint } from "./fixtures";

const mocked = vi.mocked(api);

function series(points = [dailyPoint("2026-11-01"), dailyPoint("2026-11-02")]) {
  return { days: points.length, timezone: "UTC", series: points };
}

describe("activity card", () => {
  it("starts at 14 days and refetches when another range is chosen", async () => {
    mocked.timeseries.mockResolvedValue(series());
    const user = userEvent.setup();
    render(<Activity />);
    expect(await screen.findByText("No runs in the last 14 days.")).toBeInTheDocument();
    expect(mocked.timeseries).toHaveBeenCalledWith(14);
    expect(screen.getByRole("button", { name: "14d" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "90d" }));

    await waitFor(() => expect(mocked.timeseries).toHaveBeenLastCalledWith(90));
    expect(screen.getByRole("button", { name: "90d" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "14d" })).toHaveAttribute("aria-pressed", "false");
    expect(await screen.findByText("No runs in the last 90 days.")).toBeInTheDocument();
  });

  it("states runs with unknown pricing instead of counting them as zero cost", async () => {
    mocked.timeseries.mockResolvedValue(
      series([
        dailyPoint("2026-11-01", {
          runs: 2,
          succeeded: 2,
          known_cost_usd: 0.5,
          mean_duration_seconds: 4,
          timed_runs: 2,
        }),
        dailyPoint("2026-11-02", {
          runs: 1,
          failed: 1,
          known_cost_usd: null,
          runs_with_unknown_cost: 1,
          mean_duration_seconds: 2,
          timed_runs: 1,
        }),
      ]),
    );
    render(<Activity />);

    expect(await screen.findByText("3 runs · 2 succeeded · 1 failed")).toBeInTheDocument();
    expect(screen.getByText(/1 run with unknown pricing not included/)).toBeInTheDocument();

    // the table lists the newest day first; its cost reads "unknown", not $0
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const newest = within(rows[0] as HTMLElement).getAllByRole("cell");
    expect(newest[1]).toHaveTextContent("1");
    expect(newest[6]).toHaveTextContent("unknown");
    expect(newest[7]).toHaveTextContent("1");
    const oldest = within(rows[1] as HTMLElement).getAllByRole("cell");
    expect(oldest[6]).toHaveTextContent("$0.50");
  });

  it("shows the API error in place of the charts", async () => {
    mocked.timeseries.mockRejectedValue(new Error("request failed with status 500"));
    render(<Activity />);
    expect(await screen.findByText("request failed with status 500")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
