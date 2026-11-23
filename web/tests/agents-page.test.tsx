import "./mocks";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentsPage from "@/app/agents/page";
import { api } from "@/lib/api";

import { agent, agentConfig } from "./fixtures";

const mocked = vi.mocked(api);
const editor = () => screen.getByRole("textbox", { name: /agent configuration/i });

async function openForm() {
  const user = userEvent.setup();
  render(<AgentsPage />);
  await user.click(await screen.findByRole("button", { name: "New agent" }));
  return user;
}

async function typeDraft(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.clear(editor());
  // paste, not type: user-event reads `{` and `[` in typed text as key syntax
  await user.click(editor());
  if (text) await user.paste(text);
}

beforeEach(() => {
  mocked.agents.mockResolvedValue([]);
});

describe("agents page", () => {
  it("lists stored agents with model, sandbox and version", async () => {
    mocked.agents.mockResolvedValue([agent({ name: "fixer", version: 4 })]);
    render(<AgentsPage />);
    expect(await screen.findByRole("link", { name: "fixer" })).toHaveAttribute("href", "/agents/agent_1");
    expect(screen.getByText("scripted/demo")).toBeInTheDocument();
    expect(screen.getByText("v4")).toBeInTheDocument();
  });

  it("shows the empty state, and the API error instead of the table", async () => {
    const { unmount } = render(<AgentsPage />);
    expect(await screen.findByText(/No agents yet/)).toBeInTheDocument();
    unmount();

    mocked.agents.mockRejectedValue(new Error("cannot reach the AgentForge API at http://x"));
    render(<AgentsPage />);
    expect(await screen.findByText(/cannot reach the AgentForge API/)).toBeInTheDocument();
    expect(screen.queryByText(/No agents yet/)).not.toBeInTheDocument();
  });

  it("creates an agent from a JSON draft without asking the API to parse it", async () => {
    const config = agentConfig({ name: "from-json" });
    mocked.createAgent.mockResolvedValue(agent({ name: "from-json" }));
    const user = await openForm();
    await typeDraft(user, JSON.stringify(config));
    expect(screen.getByText("Read as JSON")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(mocked.createAgent).toHaveBeenCalledWith(config));
    expect(mocked.parseAgentConfig).not.toHaveBeenCalled();
    // the form closes and the list is fetched again
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(mocked.agents).toHaveBeenCalledTimes(2);
  });

  it("sends a YAML draft to the parse endpoint and stores what it returns", async () => {
    const config = agentConfig({ name: "from-yaml" });
    mocked.parseAgentConfig.mockResolvedValue(config);
    mocked.createAgent.mockResolvedValue(agent({ name: "from-yaml" }));
    const user = await openForm();
    const yaml = "name: from-yaml\nmodel:\n  provider: scripted\n";
    await typeDraft(user, yaml);
    expect(screen.getByText("Read as YAML")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(mocked.createAgent).toHaveBeenCalledWith(config));
    expect(mocked.parseAgentConfig).toHaveBeenCalledWith(yaml);
  });

  it("reports broken JSON and an empty draft without calling the API", async () => {
    const user = await openForm();
    await typeDraft(user, '{"name": ');
    await user.click(screen.getByRole("button", { name: "Create agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not valid JSON/);

    await typeDraft(user, "");
    await user.click(screen.getByRole("button", { name: "Create agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Paste or import a configuration first.");

    expect(mocked.createAgent).not.toHaveBeenCalled();
    expect(mocked.parseAgentConfig).not.toHaveBeenCalled();
  });

  it("keeps the form and the draft open when the API rejects the configuration", async () => {
    mocked.parseAgentConfig.mockRejectedValue(new Error("YAML aliases are not accepted"));
    const user = await openForm();
    await typeDraft(user, "a: &x 1\nb: *x\n");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("YAML aliases are not accepted");
    expect(editor()).toHaveValue("a: &x 1\nb: *x\n");
    expect(mocked.createAgent).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Create agent" })).toBeEnabled();
  });

  it("loads an imported file into the editor and says nothing is stored yet", async () => {
    const user = await openForm();
    const file = new File(["name: imported\n"], "agent.yaml", { type: "application/yaml" });
    await user.upload(screen.getByLabelText("Agent configuration file"), file);

    await waitFor(() => expect(editor()).toHaveValue("name: imported\n"));
    expect(screen.getByRole("status")).toHaveTextContent(/Loaded agent.yaml\. Nothing is stored/);
    expect(mocked.createAgent).not.toHaveBeenCalled();
    expect(mocked.parseAgentConfig).not.toHaveBeenCalled();
  });

  it("refuses a file of the wrong type and leaves the draft alone", async () => {
    // applyAccept: false — a user can still pick any file from the dialog
    const user = userEvent.setup({ applyAccept: false });
    render(<AgentsPage />);
    await user.click(await screen.findByRole("button", { name: "New agent" }));
    const before = (editor() as HTMLTextAreaElement).value;
    await user.upload(
      screen.getByLabelText("Agent configuration file"),
      new File(["x"], "notes.txt", { type: "text/plain" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/notes.txt: choose a .yaml, .yml or .json file/);
    expect(editor()).toHaveValue(before);
  });
});
