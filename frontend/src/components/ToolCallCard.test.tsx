import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import ToolCallCard from "./ToolCallCard";
import type { ToolCard } from "../client/types";

const base: ToolCard = { callId: "c", tool: "find_tasks", server: "archon", args: { q: "a" }, status: "done" };

test("done card expands output", async () => {
  render(<ToolCallCard card={{ ...base, output: { n: 1 } }} send={vi.fn()} />);
  expect(screen.getByText("done")).toBeTruthy();
  expect(screen.queryByText(/"n": 1/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: /output/ }));
  expect(screen.getByText(/"n": 1/)).toBeTruthy();
});

test("string output is shown plain", async () => {
  render(<ToolCallCard card={{ ...base, output: "hello" }} send={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: /output/ }));
  expect(screen.getByText("hello")).toBeTruthy();
});

test("failed card shows message", () => {
  render(<ToolCallCard card={{ ...base, status: "failed", errorMessage: "boom" }} send={vi.fn()} />);
  expect(screen.getByText("failed: boom")).toBeTruthy();
});

test("running and denied statuses", () => {
  const { unmount } = render(<ToolCallCard card={{ ...base, status: "running" }} send={vi.fn()} />);
  expect(screen.getByText("running…")).toBeTruthy();
  unmount();
  render(<ToolCallCard card={{ ...base, status: "denied" }} send={vi.fn()} />);
  expect(screen.getByText("denied")).toBeTruthy();
});

test("test_long_output_clipped_with_show_all", async () => {
  const long = "x".repeat(5000);
  render(<ToolCallCard card={{ ...base, output: long }} send={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: /output/ }));
  expect(screen.getByText(/^x+…$/).textContent!.length).toBeLessThan(2100);
  await userEvent.click(screen.getByRole("button", { name: "show all" }));
  expect(screen.getByText(long)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "show all" })).toBeNull();
});

test("circular output does not throw", async () => {
  const o: Record<string, unknown> = {}; o.self = o;
  render(<ToolCallCard card={{ ...base, output: o }} send={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: /output/ }));
  expect(screen.getByText("done")).toBeTruthy();
});

test("asking card renders the permission card", () => {
  render(<ToolCallCard send={vi.fn()} card={{ ...base, status: "asking", permission: {
    argsSummary: {}, expiresInS: 60, askedAt: Date.now(), canTrust: false, claims: [] } }} />);
  expect(screen.getByRole("button", { name: "Allow once" })).toBeTruthy();
});

test.each([
  ["cancelled", "denied", "Cancelled"],
  ["timed_out", "denied", "Timed out — denied"],
  ["trusted_tool", "running", "Trusted this tool"],
  ["trusted_server", "running", "Trusted this server"],
  ["denied", "denied", "Denied"],
  ["allowed", "running", "Allowed"],
] as const)("resolved card shows outcome %s", (outcome, st, label) => {
  render(<ToolCallCard send={vi.fn()} card={{ ...base, status: st, outcome }} />);
  expect(screen.getByText(label)).toBeTruthy();
  expect(screen.queryAllByRole("button", { name: "Allow once" })).toHaveLength(0);
});

test("trust_failed then done shows the note and the result", async () => {
  render(<ToolCallCard send={vi.fn()} card={{ ...base, status: "done", outcome: "trust_failed", output: { n: 7 } }} />);
  expect(screen.getByText("Allowed — couldn't save trust — it will ask again")).toBeTruthy();
  expect(screen.getByText("done")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /output/ }));
  expect(screen.getByText(/"n": 7/)).toBeTruthy();
});
