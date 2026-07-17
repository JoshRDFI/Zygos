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
}

export interface RuntimeHealth {
  routes: { provider: string; model: string; circuit: string }[];
  embedder: { backend: string; model: string; state: string };
  active_sessions: number;
}
