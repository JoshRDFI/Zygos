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
}

export interface Fit {
  level: FitLevel;
  needs: FitEstimate;
  vram_available_bytes: number | null;
  ram_available_bytes: number | null;
  reason: string;
}

export type ProfileSource = "user" | "eval" | "measured" | "modelfile" | "ollama" | "name";

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
}

export interface ModelsView {
  hardware: HardwareSnapshot | null;
  ollama: { configured: boolean; reachable: boolean; error: string | null };
  models: ModelEntry[];
}

export interface RuntimeHealth {
  routes: { provider: string; model: string; circuit: string }[];
  embedder: { backend: string; model: string; state: string };
  active_sessions: number;
}
