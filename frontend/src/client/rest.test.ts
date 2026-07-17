import { afterEach, expect, test, vi } from "vitest";
import { createSession, getHealth, getManifest } from "./rest";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => body }) as Response));
}

test("createSession posts to /sessions and returns the id", async () => {
  stubFetch({ id: "sess-1" });
  expect(await createSession()).toBe("sess-1");
  expect(fetch).toHaveBeenCalledWith("/sessions", { method: "POST" });
});

test("getManifest gets /runtime", async () => {
  stubFetch({ lifecycle_stage: "running" });
  const m = await getManifest();
  expect(m.lifecycle_stage).toBe("running");
  expect(fetch).toHaveBeenCalledWith("/runtime");
});

test("getHealth adds probe query when requested", async () => {
  stubFetch({ active_sessions: 0 });
  await getHealth(true);
  expect(fetch).toHaveBeenCalledWith("/runtime/health?probe=true");
});
