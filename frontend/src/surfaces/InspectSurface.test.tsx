import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import InspectSurface from "./InspectSurface";
import * as rest from "../client/rest";
import { useThinkStore } from "../stores/thinkStore";
import type { Manifest } from "../client/types";

beforeEach(() => {
  useThinkStore.getState().reset();
  Element.prototype.scrollIntoView = vi.fn();
  vi.spyOn(rest, "getManifest").mockResolvedValue({
    lifecycle_stage: "running",
    capabilities: {},
    plugins: [{ kind: "provider", name: "primary", module: "zygos.providers.ollama:Ollama" }],
    primary_route: { provider: "ollama", model: "qwen3" },
    fallback_routes: [],
    reasoning_enabled: false,
    versions: { zygos: "0.1.0", python: "3.12.0" },
    voice: null, thinking: null,
  });
});
afterEach(() => vi.restoreAllMocks());

test("renders live manifest fields", async () => {
  render(<InspectSurface />);
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  expect(screen.getByText(/qwen3/)).toBeInTheDocument();
  expect(screen.getByText(/zygos.providers.ollama:Ollama/)).toBeInTheDocument();
});

const ev = (turnId: string, index: number, text: string, extra = {}) => ({
  turnId, step: "direct", index, text, truncated: false, chars: text.length, elapsedMs: 12, ...extra,
});

test("thinking section lists turns and events", async () => {
  useThinkStore.setState({
    eventsByTurn: { a: [ev("a", 0, "first thought")], b: [ev("b", 1, "second thought")] },
    turnOrder: ["a", "b"],
  });
  render(<InspectSurface />);
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "thinking" })).toBeInTheDocument();
  expect(screen.getByText("direct #0 · 12 ms")).toBeInTheDocument();
  expect(screen.getByText("first thought").tagName).toBe("PRE");
  expect(screen.getByText("second thought")).toBeInTheDocument();
});

test("truncated event shows the dropped character count", async () => {
  useThinkStore.setState({
    eventsByTurn: { a: [ev("a", 0, "x".repeat(32000), { truncated: true, chars: 40000 })] },
    turnOrder: ["a"],
  });
  render(<InspectSurface />);
  expect(await screen.findByText("… 8000 earlier characters not kept")).toBeInTheDocument();
});

test("selected turn is marked current and scrolled into view", async () => {
  useThinkStore.setState({
    eventsByTurn: { a: [ev("a", 0, "one")], b: [ev("b", 0, "two")] },
    turnOrder: ["a", "b"], selectedTurnId: "b",
  });
  const { container } = render(<InspectSurface />);
  await waitFor(() => expect(container.querySelector('[aria-current="true"]')).not.toBeNull());
  expect(container.querySelector('[aria-current="true"]')).toHaveTextContent("two");
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
});

test("empty state when no thinking recorded", async () => {
  render(<InspectSurface />);
  expect(await screen.findByText("No thinking recorded yet.")).toBeInTheDocument();
});

test("manifest thinking line: supported and unavailable", async () => {
  const base = await rest.getManifest();
  vi.spyOn(rest, "getManifest").mockResolvedValue({ ...base, thinking: { supported: true, reason: null } } as Manifest);
  const r = render(<InspectSurface />);
  expect(await screen.findByText("thinking: supported")).toBeInTheDocument();
  r.unmount();
  vi.spyOn(rest, "getManifest").mockResolvedValue({ ...base, thinking: { supported: false, reason: "m can't think" } } as Manifest);
  render(<InspectSurface />);
  expect(await screen.findByText("thinking: unavailable — m can't think")).toBeInTheDocument();
});

test("speech section: empty state and timing lines", async () => {
  const { useSpeechStore } = await import("../stores/speechStore");
  useSpeechStore.getState().reset();
  render(<InspectSurface />);
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "speech" })).toBeInTheDocument();
  expect(screen.getByText("No spoken replies yet.")).toBeInTheDocument();
  useSpeechStore.setState({ timings: [{ turnId: "t1", firstAudioMs: 1830, wordsAtStart: 14, rateWps: 52, gaps: 0, gapMs: 0, reason: "complete" }] });
  await waitFor(() =>
    expect(screen.getByText("first word 1.8 s · started after 14 words at 52 w/s · no gaps")).toBeInTheDocument());
  useSpeechStore.getState().reset();
});

test("model section: empty state, then chosen/loaded/skipped lines", async () => {
  const { useModelTraceStore } = await import("../stores/modelTraceStore");
  useModelTraceStore.getState().reset();
  render(<InspectSurface />);
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "models" })).toBeInTheDocument();
  expect(screen.getByText("No model choices recorded yet.")).toBeInTheDocument();
  useModelTraceStore.setState({ lines: [
    { kind: "chosen", turnId: "t", category: "chat", provider: "other", model: "s", reason: "saved default" },
    { kind: "loaded", provider: "ollama", model: "q", loadMs: 5, evicted: [] },
    { kind: "skipped", provider: "ollama", model: "q", reason: "load_failed" },
  ] });
  await waitFor(() => expect(screen.getByText("chat: other/s — saved default")).toBeInTheDocument());
  expect(screen.getByText("loaded ollama/q in 5 ms")).toBeInTheDocument();
  expect(screen.getByText("skipped ollama/q: load_failed")).toBeInTheDocument();
  useModelTraceStore.getState().reset();
});
