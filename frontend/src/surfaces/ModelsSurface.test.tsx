import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ModelsSurface from "./ModelsSurface";
import * as rest from "../client/rest";
import type { ModelEntry, ModelsView } from "../client/types";

const GB = 1024 ** 3;
const est = { model_bytes: 5 * GB, context_bytes: GB, context_tokens: 4096, context_assumed: true, overhead_bytes: 0, total_bytes: 6 * GB, measured: false };

function entry(over: Partial<ModelEntry>): ModelEntry {
  return {
    provider: "ollama", name: "m", location: "local", family: null, parameter_size: null,
    quantization: null, specialty: [], capabilities: {}, download_size_bytes: null,
    loaded: false, vram_bytes: null, fit: null, fit_text: null, primary: false,
    fallback: false, profile_error: null, fields: {}, ...over,
  };
}

function view(over: Partial<ModelsView> = {}): ModelsView {
  return {
    hardware: {
      gpus: [{ name: "RTX 5080", vram_total_bytes: 16 * GB, vram_free_bytes: 12 * GB }],
      ram_total_bytes: 32 * GB, ram_available_bytes: 20 * GB,
      cpu_model: "Ryzen 7 3700X", cpu_cores: 16, disk_path: "/", disk_free_bytes: null,
      scanned_at: "2026-11-04T00:00:00Z",
    },
    ollama: { configured: true, reachable: true, error: null },
    models: [
      entry({ name: "qwen3:8b", family: "qwen3", download_size_bytes: 5.2 * GB, quantization: "Q4_K_M",
        specialty: ["reasoning"], capabilities: { tools: true, vision: false }, loaded: true, vram_bytes: 6 * GB,
        primary: true, fit: { level: "gpu", needs: est, vram_available_bytes: 12 * GB, ram_available_bytes: null, reason: "r" },
        fit_text: "fits on the GPU",
        fields: {
          "identity.family": { value: "qwen3", source: "ollama", at: "2026-11-04T12:00:00Z" },
          "identity.num_ctx": { value: 8192, source: "modelfile", at: "2026-11-03T09:30:00Z" },
          "user.notes": { value: "my daily driver", source: "user", at: null },
        } }),
      entry({ name: "qwen3:14b", family: "qwen3", fallback: true,
        fit: { level: "partial", needs: est, vram_available_bytes: 12 * GB, ram_available_bytes: null, reason: "r" },
        fit_text: "needs partial offload" }),
      entry({ name: "broken:1b", profile_error: "profile file can't be read: Expecting value" }),
      entry({ name: "ro:1b", profile_error: "profile can't be saved: [Errno 13] Permission denied" }),
      entry({ provider: "vllm", name: "meta-llama", fit_text: "fit not checked for vllm" }),
      entry({ provider: "anthropic", name: "claude-sonnet-5", location: "cloud", fit_text: "fit doesn't apply (cloud)" }),
    ],
    ...over,
  };
}

beforeEach(() => { vi.spyOn(rest, "getModels").mockResolvedValue(view()); });
afterEach(() => vi.restoreAllMocks());

test("renders hardware with unknown for null fields and summed VRAM", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText(/RTX 5080/)).toBeInTheDocument());
  expect(screen.getByText(/12\.0 \/ 16\.0 GB/)).toBeInTheDocument();
  expect(screen.getByText(/16 threads/)).toBeInTheDocument();
  expect(screen.getByText(/Disk free:.*unknown/)).toBeInTheDocument();
});

test("groups variants by family and shows details", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByRole("heading", { name: "qwen3" })).toBeInTheDocument());
  expect(screen.getAllByRole("heading", { name: "qwen3" })).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "other" })).toBeInTheDocument();
  expect(screen.getByText("5.2 GB")).toBeInTheDocument();
  expect(screen.getByText("Q4_K_M")).toBeInTheDocument();
  expect(screen.getByText("reasoning")).toBeInTheDocument();
  expect(screen.getByText("tools")).toBeInTheDocument();
  expect(screen.queryByText("vision")).not.toBeInTheDocument();
  expect(screen.getByText(/loaded · 6\.0 GB VRAM/)).toBeInTheDocument();
  expect(screen.getByText("primary")).toBeInTheDocument();
  expect(screen.getByText("fallback")).toBeInTheDocument();
});

test("shows fit level and fit text", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText("gpu")).toBeInTheDocument());
  expect(screen.getByText("partial")).toBeInTheDocument();
  expect(screen.getByText("fits on the GPU")).toBeInTheDocument();
  expect(screen.getByText("needs partial offload")).toBeInTheDocument();
});

test("non-Ollama local route is local, with its fit_text", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText("fit not checked for vllm")).toBeInTheDocument());
  expect(screen.getByText(/meta-llama/)).toBeInTheDocument();
});

test("cloud route says fit does not apply", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText("fit doesn't apply (cloud)")).toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "cloud" })).toBeInTheDocument();
});

test("shows a profile_error as the backend words it", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText("profile file can't be read: Expecting value")).toBeInTheDocument());
  expect(screen.getByText("profile can't be saved: [Errno 13] Permission denied")).toBeInTheDocument();
});

test("lists each profile field with its source and date, collapsed by default", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText("fits on the GPU")).toBeInTheDocument());
  const summary = screen.getByText("profile");
  const details = summary.closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(screen.getAllByText("profile")).toHaveLength(1); // only rows with fields get one
  fireEvent.click(summary);
  expect(details).toHaveAttribute("open");
  expect(within(details).getByText("identity.family · qwen3 · ollama · 2026-11-04")).toBeInTheDocument();
  expect(within(details).getByText("identity.num_ctx · 8192 · modelfile · 2026-11-03")).toBeInTheDocument();
  expect(within(details).getByText("user.notes · my daily driver · your edit")).toBeInTheDocument();
});

test("says Ollama is unreachable with the error instead of spinning", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(
    view({ ollama: { configured: true, reachable: false, error: "connection refused" }, models: [] }));
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText(/Ollama is unreachable/)).toBeInTheDocument());
  expect(screen.getByText(/connection refused/)).toBeInTheDocument();
  expect(screen.queryByText(/Loading/)).not.toBeInTheDocument();
});

test("a failed request shows an error rather than loading forever", async () => {
  vi.spyOn(rest, "getModels").mockRejectedValue(new Error("request failed: 500"));
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText(/request failed: 500/)).toBeInTheDocument());
});

test("notes that choosing and downloading come next", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText("Choosing a default model and downloading models come next.")).toBeInTheDocument());
  expect(screen.queryByText(/coming later/i)).not.toBeInTheDocument();
});
