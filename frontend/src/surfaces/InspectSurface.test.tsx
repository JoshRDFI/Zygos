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
