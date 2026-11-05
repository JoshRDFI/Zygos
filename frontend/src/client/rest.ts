import type { BackendsView, Manifest, ModelsView, RuntimeHealth } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  return (await res.json()) as T;
}

export async function createSession(): Promise<string> {
  const res = await fetch("/sessions", { method: "POST" });
  const body = await json<{ id: string }>(res);
  return body.id;
}

export async function getManifest(): Promise<Manifest> {
  return json<Manifest>(await fetch("/runtime"));
}

export async function getHealth(probe = false): Promise<RuntimeHealth> {
  return json<RuntimeHealth>(await fetch(`/runtime/health${probe ? "?probe=true" : ""}`));
}

export async function getModels(): Promise<ModelsView> {
  return json<ModelsView>(await fetch("/models"));
}

export async function getBackends(): Promise<BackendsView> {
  return json<BackendsView>(await fetch("/backends"));
}

/** A refused PUT /models/default: `needsConfirm` means the user may override (poor fit). */
export class DefaultModelError extends Error {
  constructor(readonly status: number, readonly detail: string, readonly needsConfirm: boolean) {
    super(detail);
  }
}

export async function setDefaultModel(provider: string, model: string, confirm = false): Promise<ModelsView> {
  const res = await fetch("/models/default", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, model, confirm }),
  });
  if (res.ok) return (await res.json()) as ModelsView;
  let body: { detail?: unknown; needs_confirm?: unknown } = {};
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  const detail = typeof body.detail === "string" ? body.detail : `request failed: ${res.status}`;
  throw new DefaultModelError(res.status, detail, body.needs_confirm === true);
}

export async function resetDefaultModel(): Promise<ModelsView> {
  return json<ModelsView>(await fetch("/models/default", { method: "DELETE" }));
}
