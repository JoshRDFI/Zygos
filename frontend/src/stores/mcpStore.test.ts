import { beforeEach, expect, test, vi } from "vitest";

vi.mock("../client/mcp", async (orig) => ({ ...(await orig<typeof import("../client/mcp")>()), getMcp: vi.fn() }));
import { McpError, getMcp } from "../client/mcp";
import type { McpView } from "../client/types";
import { useMcpStore } from "./mcpStore";

const view = (tools_on: number): McpView => ({ installed: true, servers: [], tools_on, warn: false, warning: null });

beforeEach(() => {
  vi.mocked(getMcp).mockReset();
  useMcpStore.setState({ view: null, loading: false, loadError: null, busy: null, errors: {}, notes: {} });
});

test("load stores the view and reports a failure", async () => {
  vi.mocked(getMcp).mockResolvedValueOnce(view(1));
  await useMcpStore.getState().load();
  expect(useMcpStore.getState().view?.tools_on).toBe(1);
  vi.mocked(getMcp).mockRejectedValueOnce(new McpError(503, "record unavailable"));
  await useMcpStore.getState().load();
  expect(useMcpStore.getState().loadError).toBe("record unavailable");
  expect(useMcpStore.getState().loading).toBe(false);
});

test("run stores the view", async () => {
  await useMcpStore.getState().run("k", async () => view(3));
  const s = useMcpStore.getState();
  expect(s.view?.tools_on).toBe(3);
  expect(s.busy).toBeNull();
});

test("run sets busy while the action runs", async () => {
  let release!: (v: McpView) => void;
  const p = useMcpStore.getState().run("server:a:on", () => new Promise<McpView>((r) => { release = r; }));
  expect(useMcpStore.getState().busy).toBe("server:a:on");
  release(view(0));
  await p;
  expect(useMcpStore.getState().busy).toBeNull();
});

test("run records the error under its key", async () => {
  await useMcpStore.getState().run("k", async () => { throw new McpError(422, "bad timeout"); });
  expect(useMcpStore.getState().errors).toEqual({ k: "bad timeout" });
});

test("a later run clears the key's error and notes", async () => {
  useMcpStore.setState({ errors: { k: "old", other: "keep" }, notes: { k: ["old note"] } });
  await useMcpStore.getState().run("k", async () => view(1));
  const s = useMcpStore.getState();
  expect(s.errors).toEqual({ other: "keep" });
  expect(s.notes.k).toBeUndefined();
});

test("404 reloads", async () => {
  vi.mocked(getMcp).mockResolvedValueOnce(view(9));
  await useMcpStore.getState().run("k", async () => { throw new McpError(404, "no server x"); });
  expect(getMcp).toHaveBeenCalledTimes(1);
  const s = useMcpStore.getState();
  expect(s.errors.k).toBe("no server x");
  expect(s.view?.tools_on).toBe(9);
});

test("other errors do not reload", async () => {
  await useMcpStore.getState().run("k", async () => { throw new McpError(409, "changed"); });
  expect(getMcp).not.toHaveBeenCalled();
});

test("busy clears on failure", async () => {
  await useMcpStore.getState().run("k", async () => { throw new McpError(503, "down"); });
  expect(useMcpStore.getState().busy).toBeNull();
  await useMcpStore.getState().run("k2", async () => { throw new Error("network"); });
  expect(useMcpStore.getState().busy).toBeNull();
  expect(useMcpStore.getState().errors.k2).toBe("network");
});

test("run keeps the notes an action returns, per key", async () => {
  await useMcpStore.getState().run("server:a:remove", async () => ({ view: view(2), notes: ["kept a secret"] }));
  const s = useMcpStore.getState();
  expect(s.view?.tools_on).toBe(2);
  expect(s.notes["server:a:remove"]).toEqual(["kept a secret"]);
});

test("run drops empty notes", async () => {
  await useMcpStore.getState().run("k", async () => ({ view: view(2), notes: [] }));
  expect(useMcpStore.getState().notes.k).toBeUndefined();
});
