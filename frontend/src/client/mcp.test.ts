import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  FORBIDDEN_TEXT, McpError, getMcp, planAdd, refreshMcp, removeServer, saveServers, setSecret,
  setServerOn, setServerTrust, setTimeout_, setToolOn, setToolTrust,
} from "./mcp";
import type { McpView } from "./types";

const VIEW: McpView = { installed: true, servers: [], tools_on: 0, warn: false, warning: null };

const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown) =>
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), { status }));
const call = () => fetchMock.mock.calls[0] as [string, RequestInit | undefined];

test("encodes names in paths", async () => {
  reply(200, VIEW);
  await setServerOn("a/b c", true);
  expect(call()[0]).toBe("/mcp/servers/a%2Fb%20c/on");
  expect(call()[1]?.method).toBe("PUT");
});

test("encodes tool and secret names too", async () => {
  reply(200, VIEW); await setToolOn("a b/1", "a b__t/x", false);
  expect(call()[0]).toBe("/mcp/tools/a%20b__t%2Fx/off?server=a%20b%2F1");
  fetchMock.mockClear();
  reply(200, VIEW); await setSecret("s/1", "K 1", "v");
  expect(call()[0]).toBe("/mcp/servers/s%2F1/secrets/K%201");
});

test("maps 403 to the forbidden text", async () => {
  reply(403, { detail: "bad origin" });
  const err = await getMcp().catch((e) => e);
  expect(err).toBeInstanceOf(McpError);
  expect(err.status).toBe(403);
  expect(err.detail).toBe(FORBIDDEN_TEXT);
});

test("uses detail from error bodies", async () => {
  reply(404, { detail: "no server x" });
  const err = await setServerOn("x", true).catch((e) => e);
  expect([err.status, err.detail]).toEqual([404, "no server x"]);
});

test("falls back to a status message without a usable detail", async () => {
  fetchMock.mockResolvedValueOnce(new Response("<html>", { status: 502 }));
  expect((await getMcp().catch((e) => e)).detail).toBe("request failed: 502");
  reply(422, { detail: [{ msg: "x" }] });
  expect((await getMcp().catch((e) => e)).detail).toBe("request failed: 422");
});

test("keeps the notes an all-refused save carries", async () => {
  reply(422, { detail: "bad", notes: ["a: not added — bad"] });
  const err = await saveServers("{}", []).catch((e) => e);
  expect(err.notes).toEqual(["a: not added — bad"]);
});

test("setSecret sends the value once and never returns it", async () => {
  reply(200, VIEW);
  const out = await setSecret("srv", "TOKEN", "hunter2-marker");
  const [url, init] = call();
  expect(url).toBe("/mcp/servers/srv/secrets/TOKEN");
  expect(init?.method).toBe("PUT");
  expect(JSON.parse(init?.body as string)).toEqual({ value: "hunter2-marker" });
  expect(JSON.stringify(out)).not.toContain("hunter2-marker");
  expect(JSON.stringify(out)).toBe(JSON.stringify(VIEW));
});

test("planAdd and saveServers send their bodies", async () => {
  reply(200, { servers: [], problems: [] });
  await planAdd("{}");
  expect(call()[0]).toBe("/mcp/plan");
  expect(JSON.parse(call()[1]?.body as string)).toEqual({ text: "{}" });
  fetchMock.mockClear();
  reply(200, { view: VIEW, notes: ["n"], listing: ["l"] });
  const out = await saveServers("{}", ["a"]);
  expect(call()[0]).toBe("/mcp/servers");
  expect(JSON.parse(call()[1]?.body as string)).toEqual({ text: "{}", confirm: true, replaces: ["a"] });
  expect(out.listing).toEqual(["l"]);
});

test("removeServer and setTimeout_ return the view with notes", async () => {
  reply(200, { view: VIEW, notes: ["gone"] });
  expect(await removeServer("a b")).toEqual({ view: VIEW, notes: ["gone"] });
  expect(call()[0]).toBe("/mcp/servers/a%20b");
  expect(call()[1]?.method).toBe("DELETE");
  fetchMock.mockClear();
  reply(200, { view: VIEW, notes: ["applies now; the server restarts"] });
  const out = await setTimeout_("s", 12);
  expect(call()[0]).toBe("/mcp/servers/s/timeout");
  expect(JSON.parse(call()[1]?.body as string)).toEqual({ timeout_s: 12 });
  expect(out.notes).toEqual(["applies now; the server restarts"]);
});

test("trust uses PUT to trust and DELETE to withdraw", async () => {
  reply(200, VIEW); await setServerTrust("s", true);
  expect([call()[0], call()[1]?.method]).toEqual(["/mcp/servers/s/trust", "PUT"]);
  fetchMock.mockClear();
  reply(200, VIEW); await setServerTrust("s", false);
  expect(call()[1]?.method).toBe("DELETE");
  fetchMock.mockClear();
  reply(200, VIEW); await setToolTrust("s", "s__t", true);
  expect([call()[0], call()[1]?.method]).toEqual(["/mcp/tools/s__t/trust?server=s", "PUT"]);
  fetchMock.mockClear();
  reply(200, VIEW); await setToolTrust("s", "s__t", false);
  expect(call()[1]?.method).toBe("DELETE");
});

test("getMcp and refreshMcp hit their routes", async () => {
  reply(200, VIEW); await getMcp();
  expect([call()[0], call()[1]?.method ?? "GET"]).toEqual(["/mcp", "GET"]);
  fetchMock.mockClear();
  reply(200, VIEW); await refreshMcp();
  expect([call()[0], call()[1]?.method]).toEqual(["/mcp/refresh", "POST"]);
});
