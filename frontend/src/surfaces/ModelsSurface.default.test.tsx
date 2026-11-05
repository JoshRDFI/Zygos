import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ModelsSurface from "./ModelsSurface";
import * as rest from "../client/rest";
import type { BackendsView, ModelEntry, ModelsView } from "../client/types";
// Real GET /models, PUT /models/default output captured from the backend routes.
import saved from "./fixtures/models-default-saved.json";
import ignored from "./fixtures/models-default-ignored.json";
import put409 from "./fixtures/put-409-confirm.json";
import put409Llama from "./fixtures/put-409-llamacpp.json";
import put404 from "./fixtures/put-404.json";
import backendsPayload from "./fixtures/backends-payload.json";

const savedView = saved as unknown as ModelsView;
const ignoredView = ignored as unknown as ModelsView;

beforeEach(() => {
  vi.spyOn(rest, "getBackends").mockResolvedValue(backendsPayload as unknown as BackendsView);
});
afterEach(() => vi.restoreAllMocks());

const row = (name: string) => screen.getByText(new RegExp(`^ollama / ${name}$`)).closest("li") as HTMLElement;

test("saved default: line, badge on the default row, no button there, Reset offered", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(savedView);
  render(<ModelsSurface />);
  expect(await screen.findByText("Default: ollama/gemma4:e4b (saved)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reset to config default" })).toBeInTheDocument();
  const r = row("gemma4:e4b");
  expect(within(r).getByText("default")).toBeInTheDocument();
  expect(within(r).queryByRole("button", { name: "Set as default" })).toBeNull();
  expect(within(row("qwen3:8b")).getByRole("button", { name: "Set as default" })).toBeInTheDocument();
});

test("ignored saved default: notice with reason, config default line, Reset offered", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(ignoredView);
  render(<ModelsSurface />);
  expect(await screen.findByText("Default: ollama/qwen3:8b (from config)")).toBeInTheDocument();
  expect(screen.getByText("Your saved default ollama/gone:7b isn't used: not installed. Using ollama/qwen3:8b.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reset to config default" })).toBeInTheDocument();
});

test("config default with nothing ignored: no Reset button", async () => {
  const v = { ...ignoredView, default: { ...ignoredView.default!, ignored: null, reason: null } };
  vi.spyOn(rest, "getModels").mockResolvedValue(v);
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/qwen3:8b (from config)");
  expect(screen.queryByRole("button", { name: "Reset to config default" })).toBeNull();
});

test("Set as default calls PUT and re-renders from the returned view without re-fetching", async () => {
  const get = vi.spyOn(rest, "getModels").mockResolvedValue(ignoredView);
  const put = vi.spyOn(rest, "setDefaultModel").mockResolvedValue(savedView);
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/qwen3:8b (from config)");
  fireEvent.click(within(row("gemma4:e4b")).getByRole("button", { name: "Set as default" }));
  expect(await screen.findByText("Default: ollama/gemma4:e4b (saved)")).toBeInTheDocument();
  expect(put).toHaveBeenCalledWith("ollama", "gemma4:e4b", false);
  expect(get).toHaveBeenCalledTimes(1);
});

test("409 needs_confirm opens the dialog; Use anyway re-sends with confirm", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(ignoredView);
  const put = vi.spyOn(rest, "setDefaultModel")
    .mockRejectedValueOnce(new rest.DefaultModelError(409, put409.detail, put409.needs_confirm))
    .mockResolvedValueOnce(savedView);
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/qwen3:8b (from config)");
  fireEvent.click(within(row("huge:405b")).getByRole("button", { name: "Set as default" }));
  const dlg = await screen.findByRole("dialog");
  expect(within(dlg).getByText(`${put409.detail}. Use huge:405b as the default anyway?`)).toBeInTheDocument();
  fireEvent.click(within(dlg).getByRole("button", { name: "Use anyway" }));
  await screen.findByText("Default: ollama/gemma4:e4b (saved)");
  expect(put).toHaveBeenLastCalledWith("ollama", "huge:405b", true);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("Cancel closes the dialog without a second PUT", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(ignoredView);
  const put = vi.spyOn(rest, "setDefaultModel")
    .mockRejectedValue(new rest.DefaultModelError(409, put409.detail, true));
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/qwen3:8b (from config)");
  fireEvent.click(within(row("huge:405b")).getByRole("button", { name: "Set as default" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(put).toHaveBeenCalledTimes(1);
});

test("409 without needs_confirm and 404 show the detail inline, no dialog", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(ignoredView);
  const put = vi.spyOn(rest, "setDefaultModel")
    .mockRejectedValueOnce(new rest.DefaultModelError(409, put409Llama.detail, false))
    .mockRejectedValueOnce(new rest.DefaultModelError(404, put404.detail, false));
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/qwen3:8b (from config)");
  fireEvent.click(within(row("mistral:latest")).getByRole("button", { name: "Set as default" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(put409Llama.detail);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(within(row("mistral:latest")).getByRole("button", { name: "Set as default" }));
  await waitFor(() => expect(screen.getByText(put404.detail)).toBeInTheDocument());
  expect(put).toHaveBeenCalledTimes(2);
});

test("Reset to config default calls DELETE and re-renders from the returned view", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(savedView);
  const reset = vi.spyOn(rest, "resetDefaultModel").mockResolvedValue(ignoredView);
  render(<ModelsSurface />);
  fireEvent.click(await screen.findByRole("button", { name: "Reset to config default" }));
  expect(await screen.findByText("Default: ollama/qwen3:8b (from config)")).toBeInTheDocument();
  expect(reset).toHaveBeenCalledTimes(1);
});

function withExtras(): ModelsView {
  const base = savedView.models[0];
  const extra = (over: Partial<ModelEntry>): ModelEntry => ({ ...base, is_default: false, fields: {}, ...over });
  return {
    ...savedView,
    models: [
      ...savedView.models,
      extra({ name: "gone:1b", fit: null, fit_text: "not installed" }),
      extra({ provider: "llamacpp", name: "tiny.gguf", family: "llama" }),
      extra({ provider: "vllm", name: "meta-llama", location: "local", fit_text: "fit not checked for vllm" }),
      extra({ provider: "anthropic", name: "claude-sonnet-5", location: "cloud", fit_text: "fit doesn't apply (cloud)" }),
    ],
  };
}

test("llama.cpp rows show the explanation, not a button; vLLM and cloud rows get the button", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(withExtras());
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/gemma4:e4b (saved)");
  const llama = screen.getByText(/^llamacpp \/ tiny\.gguf$/).closest("li") as HTMLElement;
  expect(within(llama).getByText("can answer once Zygos runs llama-server (next phase)")).toBeInTheDocument();
  expect(within(llama).queryByRole("button", { name: "Set as default" })).toBeNull();
  for (const re of [/^vllm \/ meta-llama$/, /^anthropic \/ claude-sonnet-5$/]) {
    const li = screen.getByText(re).closest("li") as HTMLElement;
    expect(within(li).getByRole("button", { name: "Set as default" })).toBeInTheDocument();
  }
});

test("Ollama rows that are not installed get no Set as default button", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(withExtras());
  render(<ModelsSurface />);
  await screen.findByText("Default: ollama/gemma4:e4b (saved)");
  expect(within(row("gone:1b")).queryByRole("button", { name: "Set as default" })).toBeNull();
});
