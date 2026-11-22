import { route, router } from "./mocks";

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunDetailPage from "@/app/runs/[id]/page";
import { api } from "@/lib/api";
import type { RunEvent } from "@/lib/live";
import type { PendingApproval } from "@/lib/types";

import { run } from "./fixtures";

// The event stream is driven by the test: `emit` delivers an event, and the
// stream stays open until the page aborts it.
const stream = vi.hoisted(() => ({
  emit: undefined as ((event: RunEvent) => void) | undefined,
  opened: 0,
}));

vi.mock("@/lib/live", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/live")>();
  return {
    ...actual,
    streamRunEvents: (_id: string, onEvent: (event: RunEvent) => void, signal: AbortSignal) => {
      stream.opened += 1;
      stream.emit = onEvent;
      return new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve()));
    },
  };
});

const mocked = vi.mocked(api);

const approval: PendingApproval = {
  call_id: "call_7",
  tool: "run_command",
  arguments: { command: "rm -rf build" },
  permissions: ["execute"],
  requested_at: "2026-11-01T10:00:01Z",
};

function event(type: string, data: Record<string, unknown> = {}): RunEvent {
  return { run_id: "run_1", type, timestamp: "2026-11-01T10:00:01Z", data };
}

beforeEach(() => {
  route.params = { id: "run_1" };
  stream.emit = undefined;
  stream.opened = 0;
});

describe("run page", () => {
  it("shows a finished run without opening the event stream or asking for approvals", async () => {
    mocked.run.mockResolvedValue(run({ result: "All done." }));
    render(<RunDetailPage />);

    expect(await screen.findByText("All done.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cancel/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Pending approval")).not.toBeInTheDocument();
    expect(stream.opened).toBe(0);
    expect(mocked.pendingApprovals).not.toHaveBeenCalled();
    // unknown pricing is named, not shown as a made-up amount
    expect(screen.getByText("Estimated cost").parentElement).toHaveTextContent("Estimated costunknown");
  });

  it("sends an approval decision for the paused call and reloads the run", async () => {
    mocked.run.mockResolvedValue(run({ status: "awaiting_approval", result: null, finished_at: null }));
    mocked.pendingApprovals.mockResolvedValue([approval]);
    mocked.decideApproval.mockResolvedValue(run({ status: "running", result: null, finished_at: null }));
    const user = userEvent.setup();
    render(<RunDetailPage />);

    expect(await screen.findByText("Pending approval")).toBeInTheDocument();
    expect(screen.getByText("run_command")).toBeInTheDocument();
    expect(screen.getByText(/rm -rf build/)).toBeInTheDocument();
    const loads = mocked.run.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(mocked.decideApproval).toHaveBeenCalledWith("run_1", "call_7", true));
    await waitFor(() => expect(mocked.run.mock.calls.length).toBeGreaterThan(loads));
  });

  it("sends a denial, and shows the API's error when the decision fails", async () => {
    mocked.run.mockResolvedValue(run({ status: "awaiting_approval", result: null, finished_at: null }));
    mocked.pendingApprovals.mockResolvedValue([approval]);
    mocked.decideApproval.mockRejectedValue(new Error("approval call_7 is no longer pending"));
    const user = userEvent.setup();
    render(<RunDetailPage />);

    await user.click(await screen.findByRole("button", { name: "Deny" }));

    await waitFor(() => expect(mocked.decideApproval).toHaveBeenCalledWith("run_1", "call_7", false));
    expect(await screen.findByText("approval call_7 is no longer pending")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("previews streamed model output while a run is active and reloads on a recorded step", async () => {
    mocked.run.mockResolvedValue(run({ status: "running", result: null, finished_at: null }));
    render(<RunDetailPage />);
    await screen.findByRole("button", { name: /Cancel/ });
    await waitFor(() => expect(stream.opened).toBe(1));
    expect(screen.queryByText(/Model output \(live/)).not.toBeInTheDocument();

    act(() => {
      stream.emit?.(event("llm.delta", { step: 2, text: "Thinking about " }));
      stream.emit?.(event("llm.delta", { step: 2, text: "the fix" }));
    });

    expect(await screen.findByText("Thinking about the fix")).toBeInTheDocument();
    expect(screen.getByText(/Model output \(live, step 2\)/)).toBeInTheDocument();

    const loads = mocked.run.mock.calls.length;
    act(() => stream.emit?.(event("step.finished", { step: 2 })));
    await waitFor(() => expect(mocked.run.mock.calls.length).toBeGreaterThan(loads));
    // the recorded step replaces the preview
    expect(screen.queryByText("Thinking about the fix")).not.toBeInTheDocument();
  });

  it("re-runs into the new run and offers the comparison on a re-run", async () => {
    mocked.run.mockResolvedValue(run({ id: "run_2", parent_run_id: "run_1" }));
    mocked.rerun.mockResolvedValue(run({ id: "run_3" }));
    route.params = { id: "run_2" };
    const user = userEvent.setup();
    render(<RunDetailPage />);

    await user.click(await screen.findByRole("button", { name: /Compare with original/ }));
    expect(router.push).toHaveBeenCalledWith("/runs/compare?a=run_1&b=run_2");

    await user.click(screen.getByRole("button", { name: /Re-run/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/runs/run_3"));
    expect(mocked.rerun).toHaveBeenCalledWith("run_2");
  });
});
