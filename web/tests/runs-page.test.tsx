import { router } from "./mocks";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import RunsPage from "@/app/runs/page";
import { api } from "@/lib/api";

import { runSummary } from "./fixtures";

const mocked = vi.mocked(api);
const tick = (id: string) => screen.getByRole("checkbox", { name: `Select run ${id} to compare` });
const compareButton = () => screen.getByRole("button", { name: /Compare \(/ });

function threeRuns() {
  mocked.runs.mockResolvedValue({
    items: ["run_a", "run_b", "run_c"].map((id) => runSummary({ id, goal: `goal of ${id}` })),
    total: 3,
  });
}

describe("runs page", () => {
  it("enables Compare only with two runs ticked and opens the comparison in tick order", async () => {
    threeRuns();
    const user = userEvent.setup();
    render(<RunsPage />);
    await screen.findByText("goal of run_a");
    expect(compareButton()).toBeDisabled();

    await user.click(tick("run_b"));
    expect(compareButton()).toBeDisabled();
    expect(compareButton()).toHaveTextContent("Compare (1/2)");

    await user.click(tick("run_a"));
    expect(compareButton()).toBeEnabled();
    await user.click(compareButton());
    expect(router.push).toHaveBeenCalledWith("/runs/compare?a=run_b&b=run_a");
  });

  it("replaces the oldest tick when a third run is ticked", async () => {
    threeRuns();
    const user = userEvent.setup();
    render(<RunsPage />);
    await screen.findByText("goal of run_a");

    await user.click(tick("run_a"));
    await user.click(tick("run_b"));
    await user.click(tick("run_c"));

    expect(tick("run_a")).not.toBeChecked();
    expect(tick("run_b")).toBeChecked();
    expect(tick("run_c")).toBeChecked();
    expect(compareButton()).toHaveTextContent("Compare (2/2)");
  });

  it("asks the API for the chosen status and keeps the ticks across the filter", async () => {
    threeRuns();
    const user = userEvent.setup();
    render(<RunsPage />);
    await screen.findByText("goal of run_a");
    expect(mocked.runs).toHaveBeenLastCalledWith({ status: "", limit: 50, offset: 0 });
    await user.click(tick("run_a"));

    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by status" }), "failed");

    await waitFor(() =>
      expect(mocked.runs).toHaveBeenLastCalledWith({ status: "failed", limit: 50, offset: 0 }),
    );
    expect(tick("run_a")).toBeChecked();
  });

  it("pages through more than fifty runs", async () => {
    mocked.runs.mockResolvedValue({ items: [runSummary()], total: 120 });
    const user = userEvent.setup();
    render(<RunsPage />);
    expect(await screen.findByText("1–50 of 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(mocked.runs).toHaveBeenLastCalledWith({ status: "", limit: 50, offset: 50 }));
    expect(await screen.findByText("51–100 of 120")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("101–120 of 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("shows a failed run's error type and an unknown cost as unknown, never as zero", async () => {
    mocked.runs.mockResolvedValue({
      items: [runSummary({ status: "failed", error_type: "MaxStepsExceeded", cost_usd: null, passed: false })],
      total: 1,
    });
    render(<RunsPage />);
    const row = (await screen.findByText("MaxStepsExceeded")).closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("unknown");
    expect(row).not.toHaveTextContent("$");
  });
});
