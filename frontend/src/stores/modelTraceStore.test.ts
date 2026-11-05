import { beforeEach, expect, test } from "vitest";
import { formatModelTrace, useModelTraceStore } from "./modelTraceStore";
import type { Frame } from "../client/types";
import frames from "./fixtures/model-turn-frames.json";

beforeEach(() => useModelTraceStore.getState().reset());
const f = (payload: Record<string, unknown>) => ({ channel: "trace", type: "event", payload }) as unknown as Frame;

test("model.chosen from a real frame reads '<category>: <p>/<m> — <reason>'", () => {
  useModelTraceStore.getState().onTrace(frames.trace_model_chosen_saved as unknown as Frame);
  expect(useModelTraceStore.getState().lines.map(formatModelTrace)).toEqual(["chat: other/s — saved default"]);
});

test("model.chosen for an ignored default carries the reason", () => {
  useModelTraceStore.getState().onTrace(frames.trace_model_chosen_ignored as unknown as Frame);
  expect(formatModelTrace(useModelTraceStore.getState().lines[0]))
    .toBe("reasoning: fake/m — saved default ignored: other/s isn't installed");
});

test("model.loaded with and without evictions; route.skipped", () => {
  const s = useModelTraceStore.getState();
  s.onTrace(f({ type: "model.loaded", provider: "ollama", model: "qwen3:8b", load_ms: 4200, evicted: [] }));
  s.onTrace(f({ type: "model.loaded", provider: "ollama", model: "qwen3:8b", load_ms: 4200, evicted: ["a:1b", "b:2b"] }));
  s.onTrace(f({ type: "route.skipped", provider: "ollama", model: "qwen3:8b", reason: "load_failed" }));
  expect(useModelTraceStore.getState().lines.map(formatModelTrace)).toEqual([
    "loaded ollama/qwen3:8b in 4200 ms",
    "loaded ollama/qwen3:8b in 4200 ms — evicted a:1b, b:2b",
    "skipped ollama/qwen3:8b: load_failed",
  ]);
});

test("ignores other trace events and caps the list", () => {
  const s = useModelTraceStore.getState();
  s.onTrace(f({ type: "route.claimed", provider: "x", model: "y" }));
  expect(useModelTraceStore.getState().lines).toHaveLength(0);
  for (let i = 0; i < 60; i++) s.onTrace(f({ type: "route.skipped", provider: "p", model: `m${i}`, reason: "r" }));
  const l = useModelTraceStore.getState().lines;
  expect(l).toHaveLength(50);
  expect(l[49]).toMatchObject({ model: "m59" });
});
