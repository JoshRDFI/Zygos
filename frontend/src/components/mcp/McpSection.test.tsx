import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import McpSection from "./McpSection";
import * as mcp from "../../client/mcp";
import { McpError, FORBIDDEN_TEXT } from "../../client/mcp";
import { useMcpStore } from "../../stores/mcpStore";
import { server, tool, view } from "./fixtures";

function show(v: ReturnType<typeof view>) {
  vi.spyOn(mcp, "getMcp").mockResolvedValue(v);
  return render(<McpSection />);
}

beforeEach(() => {
  useMcpStore.setState({ view: null, loading: false, loadError: null, busy: null, errors: {}, notes: {} });
});
afterEach(() => vi.restoreAllMocks());

test("renders every server status", async () => {
  show(view([
    server({ name: "a", status_word: "reachable", tools: [] }),
    server({ name: "b", status: "unreachable", status_word: "unreachable", detail: "connection refused", tools: [] }),
    server({ name: "c", local: true, transport: "stdio", runs: "npx -y fs", status_word: "running", tools: [] }),
    server({ name: "d", local: true, transport: "stdio", runs: "npx -y x", status_word: "stopped", exit_code: 3,
      stderr_tail: "boom on stderr", tools: [] }),
    server({ name: "e", on: false, status_word: "reachable", tools: [tool({ zname: "e__t", server_tool: "tt" })], tools_on: 1 }),
  ]));
  await screen.findByText("reachable");
  expect(screen.getByText("unreachable")).toBeInTheDocument();
  expect(screen.getByText("connection refused")).toBeInTheDocument();
  expect(screen.getByText("running")).toBeInTheDocument();
  expect(screen.getByText("stopped")).toBeInTheDocument();
  expect(screen.getByText(/exit code 3/)).toBeInTheDocument();
  expect(screen.queryByText("boom on stderr")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /stderr/ }));
  expect(screen.getByText("boom on stderr")).toBeInTheDocument();
  expect(screen.getByText("off")).toBeInTheDocument();
  expect(screen.getByText("tt").closest("li")).toHaveClass("opacity-50");
});

test("renders each tool state", async () => {
  show(view([server({ tools: [
    tool({ zname: "s__a", server_tool: "a", trust: "trusted" }),
    tool({ zname: "s__b", server_tool: "b", trust: "asks" }),
    tool({ zname: "s__c", server_tool: "c", trust: "changed", was: "old text", now: "new text" }),
    tool({ zname: "s__d", server_tool: "d", problem: "name collides with a built-in" }),
  ], tools_on: 3 })]));
  const li = async (n: string) => (await screen.findByText(n)).closest("li") as HTMLElement;
  expect(within(await li("a")).getByRole("button", { name: "untrust" })).toBeInTheDocument();
  expect(within(await li("b")).getByRole("button", { name: "trust" })).toBeInTheDocument();
  const c = await li("c");
  expect(within(c).getByRole("button", { name: "trust again" })).toBeInTheDocument();
  expect(within(c).queryByText(/old text/)).not.toBeInTheDocument();
  await userEvent.click(within(c).getByRole("button", { name: /details/ }));
  expect(within(c).getByText(/old text/)).toBeInTheDocument();
  expect(within(c).getByText(/new text/)).toBeInTheDocument();
  const d = await li("d");
  expect(within(d).getByText(/name collides/)).toBeInTheDocument();
  expect(within(d).queryByRole("checkbox")).not.toBeInTheDocument();
  expect(within(d).queryByRole("button")).not.toBeInTheDocument();
});

test("shows the warning over twenty", async () => {
  show(view([server()], { warn: true, warning: "23 tools on — small local models choose tools less reliably" }));
  expect(await screen.findByText(/23 tools on/)).toBeInTheDocument();
});

test("shows not installed", async () => {
  show(view([], { installed: false }));
  expect(await screen.findByText("MCP support not installed — pip install -e '.[mcp]'")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /add server/i })).not.toBeInTheDocument();
});

test("add flow previews then confirms", async () => {
  show(view([]));
  const plan = vi.spyOn(mcp, "planAdd").mockResolvedValue({
    servers: [{ name: "fs", transport: "stdio", runs: "npx -y fs /home", secret_names: ["TOKEN"], unused: [],
      replaces: true, old_runs: "npx old" }],
    problems: [],
  });
  const save = vi.spyOn(mcp, "saveServers").mockResolvedValue({ view: view([server({ name: "fs" })]), notes: [], listing: [] });
  await userEvent.click(await screen.findByRole("button", { name: /add server/i }));
  await userEvent.type(screen.getByLabelText("Server JSON"), "x");
  expect(plan).not.toHaveBeenCalled();
  expect(save).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(plan).toHaveBeenCalledWith("x");
  expect(await screen.findByText("This runs `npx -y fs /home` on this machine as you")).toBeInTheDocument();
  expect(screen.getByText(/TOKEN/)).toBeInTheDocument();
  expect(screen.getByText(/replaces/i)).toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(save).toHaveBeenCalledWith("x", ["fs"]);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument());
});

test("add confirm is disabled while problems remain", async () => {
  show(view([]));
  vi.spyOn(mcp, "planAdd").mockResolvedValue({ servers: [], problems: ["bad command"] });
  await userEvent.click(await screen.findByRole("button", { name: /add server/i }));
  await userEvent.type(screen.getByLabelText("Server JSON"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByText("bad command")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
});

test("remote preview shows the address", async () => {
  show(view([]));
  vi.spyOn(mcp, "planAdd").mockResolvedValue({
    servers: [{ name: "r", transport: "http", runs: "http://h/mcp", secret_names: [], unused: [], replaces: false, old_runs: null }],
    problems: [],
  });
  await userEvent.click(await screen.findByRole("button", { name: /add server/i }));
  await userEvent.type(screen.getByLabelText("Server JSON"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByText(/http:\/\/h\/mcp/)).toBeInTheDocument();
  expect(screen.queryByText(/on this machine as you/)).not.toBeInTheDocument();
});

test("secrets show only their presence", async () => {
  show(view([server({
    header_names: ["A", "B", "C"], secrets: { A: "set", B: "not set", C: "unknown" }, secret_reasons: { C: "keychain locked" },
  })]));
  expect(await screen.findByText("keychain locked", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("= not set")).toBeInTheDocument();
  expect(screen.getByText("= set")).toBeInTheDocument();
});

test("secret replace clears the value", async () => {
  show(view());
  const setSecret = vi.spyOn(mcp, "setSecret").mockResolvedValue(view());
  await userEvent.click(await screen.findByRole("button", { name: /replace/i }));
  const field = screen.getByLabelText("Authorization value") as HTMLInputElement;
  expect(field.type).toBe("password");
  await userEvent.type(field, "s3cr3t-value");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(setSecret).toHaveBeenCalledWith("archon", "Authorization", "s3cr3t-value");
  await waitFor(() => expect(screen.queryByLabelText("Authorization value")).not.toBeInTheDocument());
  expect(document.body.innerHTML).not.toContain("s3cr3t-value");
  await userEvent.click(screen.getByRole("button", { name: /replace/i }));
  expect((screen.getByLabelText("Authorization value") as HTMLInputElement).value).toBe("");
});

test("remove asks inline before calling removeServer", async () => {
  show(view());
  const rm = vi.spyOn(mcp, "removeServer").mockResolvedValue({ view: view([]), notes: ["removed its secrets"] });
  await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
  expect(rm).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(rm).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
  expect(rm).toHaveBeenCalledWith("archon");
  expect(await screen.findByText("removed its secrets")).toBeInTheDocument();
});

test("timeout edit sends a number and shows a 422 reason inline", async () => {
  show(view());
  const set = vi.spyOn(mcp, "setTimeout_").mockRejectedValue(new McpError(422, "timeout must be between 1 and 600"));
  await userEvent.click(await screen.findByRole("button", { name: /edit timeout/i }));
  const f = screen.getByLabelText("Timeout seconds");
  await userEvent.clear(f);
  await userEvent.type(f, "9999");
  await userEvent.click(screen.getByRole("button", { name: "Save timeout" }));
  expect(set).toHaveBeenCalledWith("archon", 9999);
  expect(await screen.findByText("timeout must be between 1 and 600")).toBeInTheDocument();
});

test("shows a 403 reason next to the control", async () => {
  show(view());
  vi.spyOn(mcp, "setServerOn").mockRejectedValue(new McpError(403, FORBIDDEN_TEXT));
  await userEvent.click(await screen.findByRole("checkbox", { name: "archon on" }));
  expect(await screen.findByText(FORBIDDEN_TEXT)).toBeInTheDocument();
});

test("shows a 404 reason next to the control and refreshes", async () => {
  const get = vi.spyOn(mcp, "getMcp").mockResolvedValue(view());
  render(<McpSection />);
  vi.spyOn(mcp, "setServerTrust").mockRejectedValue(new McpError(404, "no server archon"));
  await userEvent.click(await screen.findByRole("checkbox", { name: "trust archon" }));
  expect(await screen.findByText("no server archon")).toBeInTheDocument();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
});

test("controls are disabled while an action is in flight", async () => {
  show(view());
  let release!: (v: ReturnType<typeof view>) => void;
  vi.spyOn(mcp, "setServerOn").mockReturnValue(new Promise((r) => { release = r; }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "archon on" }));
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "trust archon" })).toBeDisabled();
  release(view());
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled());
});

test("tool trust and on switch call the client", async () => {
  show(view());
  const trust = vi.spyOn(mcp, "setToolTrust").mockResolvedValue(view());
  const on = vi.spyOn(mcp, "setToolOn").mockResolvedValue(view());
  await userEvent.click(await screen.findByRole("button", { name: "trust" }));
  expect(trust).toHaveBeenCalledWith("archon__find_tasks", true);
  await userEvent.click(screen.getByRole("checkbox", { name: "find_tasks on" }));
  expect(on).toHaveBeenCalledWith("archon__find_tasks", false);
});

test("refresh button calls refreshMcp", async () => {
  show(view());
  const r = vi.spyOn(mcp, "refreshMcp").mockResolvedValue(view());
  await userEvent.click(await screen.findByRole("button", { name: "Refresh" }));
  expect(r).toHaveBeenCalled();
});
