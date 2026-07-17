import type { Manifest, RuntimeHealth } from "./types";

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
