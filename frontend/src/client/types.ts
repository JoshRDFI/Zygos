export interface Frame {
  channel: string;
  type: string;
  payload: Record<string, unknown>;
}

export interface Manifest {
  lifecycle_stage: string;
  capabilities: Record<string, unknown>;
  plugins: { kind: string; name: string; module: string }[];
  primary_route: { provider: string; model: string };
  fallback_routes: { provider: string; model: string }[];
  reasoning_enabled: boolean;
  versions: Record<string, string>;
  voice: unknown | null;
  thinking: { supported: boolean; reason: string | null } | null;
  hardware?: HardwareSnapshot | null;
}

export interface Gpu { name: string; vram_total_bytes: number; vram_free_bytes: number }

export interface HardwareSnapshot {
  gpus: Gpu[] | null;
  ram_total_bytes: number | null;
  ram_available_bytes: number | null;
  cpu_model: string | null;
  cpu_cores: number | null;
  disk_path: string | null;
  disk_free_bytes: number | null;
  scanned_at: string;
}

export type FitLevel = "gpu" | "partial" | "no" | "unknown";

export interface FitEstimate {
  model_bytes: number | null;
  context_bytes: number | null;
  context_tokens: number;
  context_assumed: boolean;
  overhead_bytes: number;
  total_bytes: number | null;
  measured: boolean;
  gpu_bytes?: number | null;
  cpu_bytes?: number | null;
  split_by?: "settings" | null;
  assumptions?: string[];
  reason?: string | null;
}

export interface Fit {
  level: FitLevel;
  needs: FitEstimate;
  vram_available_bytes: number | null;
  ram_available_bytes: number | null;
  reason: string;
  gpu_bytes?: number | null;
  cpu_bytes?: number | null;
  split_by?: "settings" | null;
}

export type ProfileSource = "user" | "eval" | "measured" | "modelfile" | "ollama" | "name" | "server";

/** One profile fact and where it came from (RFC-0013 §2). `at` is null for hand-edited user values. */
export interface Sourced {
  value: unknown;
  source: ProfileSource;
  at: string | null;
}

export interface ModelEntry {
  provider: string;
  name: string;
  location: "local" | "cloud";
  family: string | null;
  parameter_size: string | null;
  quantization: string | null;
  specialty: string[];
  capabilities: Record<string, boolean>;
  download_size_bytes: number | null;
  loaded: boolean;
  vram_bytes: number | null;
  fit: Fit | null;
  fit_text: string | null;
  primary: boolean;
  fallback: boolean;
  profile_error: string | null;
  fields: Record<string, Sourced>;
  launch_text?: string | null;
  launch_source?: "model" | "default" | null;
  launch_error?: string | null;
  mmproj?: string | null;
  mmproj_ambiguous?: string[];
  served_by?: string | null;
  /** True on the row the next turn is answered by (RFC-0013 phase 2). */
  is_default?: boolean;
}

export interface ModelRoute {
  provider: string;
  model: string;
}

/** The model new turns use, and whether a saved choice is being ignored. */
export interface DefaultView {
  source: "saved" | "config";
  route: ModelRoute | null;
  ignored: ModelRoute | null;
  reason: string | null;
}

export interface Check {
  ok: boolean;
  detail: string;
}

export interface BackendsView {
  settings: {
    ollama: { base_url: string | null };
    llamacpp: { server_path: string | null; models_dir: string | null; default_args: string; model_args: Record<string, string> };
    vllm: { name: string; base_url: string }[];
  };
  /** null: no route uses Ollama and no address is recorded (not set up, not probed). */
  ollama: Check | null;
  llamacpp: { server: Check; models: Check };
  /** null: no vLLM server is recorded or routed. */
  vllm: { check: Check; served: string[] } | null;
  address_sources: Record<string, string>;
  restart_required: boolean;
}

export interface ModelsView {
  hardware: HardwareSnapshot | null;
  ollama: { configured: boolean; reachable: boolean; error: string | null };
  models: ModelEntry[];
  default?: DefaultView;
}

export interface RuntimeHealth {
  routes: { provider: string; model: string; circuit: string }[];
  embedder: { backend: string; model: string; state: string };
  active_sessions: number;
}

export type PermissionOutcome =
  "allowed" | "trusted_tool" | "trusted_server" | "denied" | "timed_out" | "cancelled" | "trust_failed";
export interface PermissionAsk {
  argsSummary: Record<string, unknown>; expiresInS: number; askedAt: number; // Date.now()
  canTrust: boolean; server?: string; serverTool?: string; where?: "local" | "remote";
  address?: string; description?: string; claims: string[]; ruleNote?: string;
  changed?: { oldDescription: string; newDescription: string; oldSchema: unknown; newSchema: unknown };
}
export interface ToolCard {
  callId: string; tool: string; server?: string; args: Record<string, unknown>;
  status: "asking" | "running" | "done" | "failed" | "denied";
  output?: unknown; errorMessage?: string;
  permission?: PermissionAsk; outcome?: PermissionOutcome;
}
