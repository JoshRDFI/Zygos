import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ModelsSurface from "./ModelsSurface";
import * as rest from "../client/rest";
import type { BackendsView, ModelEntry, ModelsView } from "../client/types";

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

const backends: BackendsView = {
  settings: {
    ollama: { base_url: null },
    llamacpp: { server_path: "/tmp/x/llama-server", models_dir: "/tmp/x/gguf", default_args: "-c 8192", model_args: {} },
    vllm: [{ name: "vllm", base_url: "http://127.0.0.1:8000/v1" }],
  },
  ollama: { ok: true, detail: "Ollama 0.9.1 at http://localhost:11434" },
  llamacpp: {
    server: { ok: true, detail: "version: 6500 (abc1234)" },
    models: { ok: true, detail: "10 GGUF files in /tmp/x/gguf" },
  },
  vllm: { check: { ok: true, detail: "1 models served at http://127.0.0.1:8000/v1" }, served: ["Qwen/Qwen3-8B"] },
  address_sources: { ollama: "default", vllm: "backends" },
  restart_required: false,
};

beforeEach(() => {
  vi.spyOn(rest, "getModels").mockResolvedValue(view());
  vi.spyOn(rest, "getBackends").mockResolvedValue(backends);
});
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

const llamaEst = { model_bytes: 943722496, context_bytes: 33554432, context_tokens: 4096, context_assumed: false, overhead_bytes: 536870912, total_bytes: 1514147840, measured: false };
const llamaBase = { provider: "llamacpp", launch_source: "default" as const, launch_error: null, mmproj: null, mmproj_ambiguous: [], served_by: null };
const splitText = "needs \u22480.8 GB on GPU + 0.6 GB in RAM (split by your settings): 0.9 GB model + 0.0 GB context (4096 tokens) + 0.5 GB overhead";

function llamaView(models: ModelEntry[], over: Partial<ModelsView> = {}): ModelsView {
  return { ...view({ models }), ...over };
}

test("Backends block shows each check's detail, marks problems, and says how to change settings", async () => {
  vi.spyOn(rest, "getBackends").mockResolvedValue({
    ...backends,
    llamacpp: { server: { ok: false, detail: "llama-server not found at /nope" }, models: backends.llamacpp.models },
  });
  render(<ModelsSurface />);
  const block = await screen.findByRole("region", { name: "Backends" });
  expect(within(block).getByText(/Ollama 0\.9\.1 at http:\/\/localhost:11434/)).toBeInTheDocument();
  expect(within(block).getByText(/10 GGUF files in/)).toBeInTheDocument();
  expect(within(block).getByText(/1 models served at http:\/\/127\.0\.0\.1:8000\/v1/)).toBeInTheDocument();
  expect(within(block).getByText(/llama-server not found at \/nope/).closest("li")).toHaveTextContent("problem");
  expect(within(block).queryByText("Restart Zygos to apply the new addresses.")).toBeNull();
  expect(screen.getByText("Change backend settings with zygos personalize backends.")).toBeInTheDocument();
});

test("restart_required shows the restart notice and where vLLM is served from", async () => {
  vi.spyOn(rest, "getBackends").mockResolvedValue({ ...backends, restart_required: true });
  vi.spyOn(rest, "getModels").mockResolvedValue(llamaView([
    entry({ provider: "vllm", name: "Qwen/Qwen3-8B", fit_text: "fit not checked: vLLM reserves its GPU share at start", served_by: "http://127.0.0.1:8000/v1" } as Partial<ModelEntry>),
  ]));
  render(<ModelsSurface />);
  expect(await screen.findByText("Restart Zygos to apply the new addresses.")).toBeInTheDocument();
  expect(screen.getByText(/served by http:\/\/127\.0\.0\.1:8000\/v1/)).toBeInTheDocument();
  expect(screen.getByText("fit not checked: vLLM reserves its GPU share at start")).toBeInTheDocument();
});

test("a failed GET /backends does not break the page", async () => {
  vi.spyOn(rest, "getBackends").mockRejectedValue(new Error("request failed: 500"));
  render(<ModelsSurface />);
  expect(await screen.findByText("Couldn't load backend status: request failed: 500")).toBeInTheDocument();
  expect(screen.getByText(/qwen3:8b/)).toBeInTheDocument();
});

test("llama.cpp rows show the served split text, own settings, and the vision projector", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(llamaView([
    entry({
      ...llamaBase, name: "gemma/gemma-3-4b-it-Q4_K_M", family: "gemma3", quantization: "Q4_K_M",
      launch_text: "-c 4096 -ngl 1", launch_source: "model", mmproj: "gemma/mmproj-gemma-3-4b-f16.gguf",
      fit: { level: "partial", needs: { ...llamaEst, gpu_bytes: 868225024, cpu_bytes: 645922816, split_by: "settings", assumptions: [], reason: null }, vram_available_bytes: 16777216000, ram_available_bytes: 32768000000, reason: "", gpu_bytes: 868225024, cpu_bytes: 645922816, split_by: "settings" },
      fit_text: splitText,
    } as Partial<ModelEntry>),
    entry({
      ...llamaBase, name: "Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M", family: "qwen3", launch_text: "-c 8192", launch_source: "default",
      fit_text: "needs \u22481.7 GB: 1.2 GB model",
    } as Partial<ModelEntry>),
  ]));
  render(<ModelsSurface />);
  expect(await screen.findByText(splitText)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "gemma3" })).toBeInTheDocument();
  const own = screen.getByText("-c 4096 -ngl 1");
  expect(own.className).toMatch(/font-mono/);
  expect(own.closest("li")).toHaveTextContent("(own settings)");
  expect(own.closest("li")).toHaveTextContent("+ vision projector");
  const def = screen.getByText("-c 8192");
  expect(def.closest("li")).toHaveTextContent("(default settings)");
  expect(def.closest("li")).not.toHaveTextContent("vision projector");
});

test("a launch settings problem is shown as the backend words it", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(llamaView([
    entry({
      ...llamaBase, name: "Llama-3.2-3B-Q8_0", family: "llama", launch_text: "-c 4096 --port=9000", launch_source: "model",
      launch_error: "--port is set by Zygos \u2014 remove it", fit_text: "launch settings: --port is set by Zygos \u2014 remove it",
    } as Partial<ModelEntry>),
  ]));
  render(<ModelsSurface />);
  expect(await screen.findByText("Launch settings problem: --port is set by Zygos \u2014 remove it")).toBeInTheDocument();
});

test("an unclear projector pairing lists the files and does not guess", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(llamaView([
    entry({
      ...llamaBase, name: "mixed/A-Q4_0", family: "qwen3", launch_text: "-c 8192",
      mmproj_ambiguous: ["mixed/mmproj-a.gguf", "mixed/mmproj-b.gguf"], fit_text: "needs \u22480.6 GB",
    } as Partial<ModelEntry>),
  ]));
  render(<ModelsSurface />);
  expect(await screen.findByText(
    "Projector unclear: mixed/mmproj-a.gguf, mixed/mmproj-b.gguf \u2014 pairing comes with the next phase",
  )).toBeInTheDocument();
  expect(screen.queryByText("+ vision projector")).toBeNull();
});

test("an unreachable vLLM entry shows the backend's reason", async () => {
  const why = "vLLM unreachable: can't read models from http://127.0.0.1:8000/v1: ConnectError: [Errno 111] Connection refused";
  vi.spyOn(rest, "getModels").mockResolvedValue(llamaView([
    entry({ provider: "vllm", name: "http://127.0.0.1:8000/v1", fit_text: why, served_by: "http://127.0.0.1:8000/v1" } as Partial<ModelEntry>),
  ]));
  render(<ModelsSurface />);
  expect(await screen.findByText(why)).toBeInTheDocument();
});

test("groups come in order Ollama, llama.cpp, vLLM, cloud", async () => {
  vi.spyOn(rest, "getModels").mockResolvedValue(llamaView([
    entry({ provider: "anthropic", name: "claude-sonnet-5", location: "cloud", fit_text: "fit doesn't apply (cloud)" }),
    entry({ provider: "vllm", name: "Qwen/Qwen3-8B", fit_text: "x", served_by: "http://v/v1" } as Partial<ModelEntry>),
    entry({ ...llamaBase, name: "g/a", family: "gemma3", launch_text: "-c 8192", fit_text: "y" } as Partial<ModelEntry>),
    entry({ name: "qwen3:8b", family: "qwen3", fit_text: "z" }),
  ]));
  render(<ModelsSurface />);
  await screen.findByText(/qwen3:8b/);
  const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(heads).toEqual(["qwen3", "gemma3", "vLLM", "cloud"]);
});
