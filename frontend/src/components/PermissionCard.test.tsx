import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import PermissionCard from "./PermissionCard";
import type { PermissionAsk, PermissionOutcome, ToolCard } from "../client/types";

function card(over: Partial<PermissionAsk> = {}, c: Partial<ToolCard> = {}): ToolCard {
  return {
    callId: "c1", tool: "find_tasks", server: "archon", args: { query: "auth" }, status: "asking",
    permission: {
      argsSummary: { query: "auth" }, expiresInS: 120, askedAt: Date.now(), canTrust: true,
      server: "archon", serverTool: "find_tasks", where: "remote", address: "http://localhost:8051/mcp",
      claims: [], ...over,
    },
    ...c,
  };
}

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.useRealTimers());

test("renders four buttons for MCP and two for built-in", () => {
  const { unmount } = render(<PermissionCard card={card()} send={vi.fn()} />);
  for (const n of ["Allow once", "Deny", "Trust this tool", "Trust this server"]) {
    expect(screen.getByRole("button", { name: n })).toBeTruthy();
  }
  unmount();
  render(<PermissionCard card={card({ canTrust: false })} send={vi.fn()} />);
  expect(screen.getAllByRole("button")).toHaveLength(2);
});

test("shows server, tool, where, address, claims and args", () => {
  render(<PermissionCard card={card({ claims: ["read-only", "idempotent"] })} send={vi.fn()} />);
  expect(screen.getByText(/archon · find_tasks/)).toBeTruthy();
  expect(screen.getByText(/remote · http:\/\/localhost:8051\/mcp/)).toBeTruthy();
  expect(screen.getByText("server says: read-only, idempotent")).toBeTruthy();
  expect(screen.getByText(/"query": "auth"/)).toBeTruthy();
});

test.each([
  ["Allow once", { decision: "allow" }],
  ["Deny", { decision: "deny" }],
  ["Trust this tool", { decision: "allow", trust: "tool" }],
  ["Trust this server", { decision: "allow", trust: "server" }],
])("%s sends the response frame", async (name, extra) => {
  const send = vi.fn();
  render(<PermissionCard card={card({}, { callId: "x:fb" })} send={send} />);
  await userEvent.click(screen.getByRole("button", { name }));
  expect(send).toHaveBeenCalledWith({
    channel: "tools", type: "permission_response", payload: { call_id: "x:fb", ...extra },
  });
});

test("buttons disable after one click", async () => {
  const send = vi.fn();
  render(<PermissionCard card={card()} send={send} />);
  await userEvent.click(screen.getByRole("button", { name: "Allow once" }));
  for (const b of screen.getAllByRole("button")) expect((b as HTMLButtonElement).disabled).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Deny" }));
  expect(send).toHaveBeenCalledTimes(1);
});

test("shows changed since you trusted it with old and new text", async () => {
  render(<PermissionCard card={card({ changed: {
    oldDescription: "OLD DESC", newDescription: "NEW DESC", oldSchema: { a: 1 }, newSchema: { b: 2 },
  } })} send={vi.fn()} />);
  expect(screen.getByText("changed since you trusted it")).toBeTruthy();
  expect(screen.getByText(/OLD DESC/)).toBeTruthy();
  expect(screen.getByText(/NEW DESC/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /schema/i }));
  expect(screen.getByText(/"a": 1/)).toBeTruthy();
  expect(screen.getByText(/"b": 2/)).toBeTruthy();
});

test("shows rule note and no trust buttons when canTrust false", () => {
  render(<PermissionCard card={card({ canTrust: false, ruleNote: "a config rule asks every time for this tool" })} send={vi.fn()} />);
  expect(screen.getByText("a config rule asks every time for this tool")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Trust this tool" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Trust this server" })).toBeNull();
});

test("countdown reaches Timed out and sends nothing", () => {
  vi.useFakeTimers();
  const send = vi.fn();
  render(<PermissionCard card={card({ expiresInS: 3, askedAt: Date.now() })} send={send} />);
  expect(screen.getByText("0:03")).toBeTruthy();
  act(() => { vi.advanceTimersByTime(1000); });
  expect(screen.getByText("0:02")).toBeTruthy();
  act(() => { vi.advanceTimersByTime(2500); });
  expect(screen.getByText("Timed out")).toBeTruthy();
  for (const b of screen.getAllByRole("button")) expect((b as HTMLButtonElement).disabled).toBe(true);
  expect(send).not.toHaveBeenCalled();
});

test.each([
  ["allowed", "Allowed"],
  ["trusted_tool", "Trusted this tool"],
  ["trusted_server", "Trusted this server"],
  ["denied", "Denied"],
  ["timed_out", "Timed out — denied"],
  ["cancelled", "Cancelled"],
  ["trust_failed", "Allowed — couldn't save trust — it will ask again"],
] as [PermissionOutcome, string][])("outcome label %s", (outcome, label) => {
  render(<PermissionCard card={card({}, { outcome, status: outcome === "allowed" ? "running" : "denied" })} send={vi.fn()} />);
  expect(screen.getByText(label)).toBeTruthy();
  expect(screen.queryAllByRole("button")).toHaveLength(0);
});
